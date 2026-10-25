"""Versioned local rule definitions and side-effect-free historical previews."""
import json
import uuid

from wici.rule_models import RuleInput, RulePreview
from wici.workspace_repository import encode, iso
from wici.workspace_service import QueryChanged


class WorkspaceRules:
    def __init__(self, workspace):
        self.workspace = workspace
        self.repo, self.db = workspace.repo, workspace.db

    @staticmethod
    def decode(row):
        item = dict(row)
        item['config'] = json.loads(item.pop('config_json'))
        item['enabled'] = bool(item['enabled'])
        item['source_hint'] = {
            'transport': 'Wspólny odczyt adsb.fi / AISStream; rzeczywiste raporty pozycji.',
            'measurement': 'Konkretny czujnik, parametr i jednostka; próg użytkownika, nie oficjalny indeks.',
            'communication': 'Oficjalne publikacje dla wskazanego obszaru administracyjnego.',
            'ukraine': 'NEPTUN; pełne bieżące odczyty, nieznany stan i luki pozostają jawne.',
        }[item['template']]
        item['monitoring_hint'] = ('Pobieranie źródeł w tle, dopóki działa serwer WICI.'
                                   if item['mode'] == 'background' else
                                   'Ocena wyłącznie nowych obserwacji dostępnych w lokalnej bazie.')
        return item

    def list(self):
        with self.repo.lock:
            return {'items': [self.decode(row) for row in self.db.execute(
                'SELECT * FROM workspace_rules ORDER BY created_at DESC,id')]}

    def detail(self, rule_id):
        with self.repo.lock:
            row = self.db.execute('SELECT * FROM workspace_rules WHERE id=?', (rule_id,)).fetchone()
            if not row:
                raise KeyError(rule_id)
            return self.decode(row)

    def _validate(self, value):
        config = value.config
        if value.template == 'transport':
            area = self.workspace.areas.detail(config['area_id'])
            if area['archived']:
                raise ValueError('Wybierz aktywny obszar')
        elif value.template == 'measurement':
            item = self.workspace.catalog.object(config['object_ref'])
            if not item:
                raise ValueError('Wybierz istniejącą stację')
            if config['object_ref'].startswith('air_quality_station:'):
                sensor = self.db.execute('SELECT * FROM station_sensors WHERE sensor_id=?', (config['sensor_id'],)).fetchone()
                if not sensor or (sensor['object_ref'], sensor['parameter'], sensor['unit']) != (
                        config['object_ref'], config['metric'], config['unit']):
                    raise ValueError('Czujnik, parametr i jednostka muszą odpowiadać katalogowi stacji')
            else:
                if config['sensor_id']:
                    raise ValueError('Wodowskaz IMGW korzysta z pustego identyfikatora czujnika')
                units = {'water_level': 'cm', 'discharge': 'm³/s', 'temperature': '°C'}
                if units.get(config['metric']) != config['unit']:
                    raise ValueError('Wybierz znany parametr i jednostkę wodowskazu')
        elif value.template == 'communication':
            from wici.geo import units
            if config['admin_code'] not in units():
                raise ValueError('Wybierz znany obszar administracyjny PRG')
        elif not self.workspace.catalog.object(config['region_ref']):
            raise ValueError('Wybierz znany region Ukrainy')

    def save(self, raw, rule_id=None):
        value = RuleInput.model_validate(raw)
        with self.repo.lock, self.db:
            self._validate(value)
            previous = self.detail(rule_id) if rule_id else None
            if previous and value.revision != previous['revision']:
                raise QueryChanged('Reguła została zmieniona w innym oknie; wczytaj aktualną wersję')
            if value.enabled and (not previous or not previous['enabled']):
                count = self.db.execute('SELECT count(*) FROM workspace_rules WHERE enabled=1').fetchone()[0]
                if count >= 50:
                    raise ValueError('Limit 50 aktywnych reguł')
            now = iso(self.repo.clock())
            identity = rule_id or str(uuid.uuid4())
            revision = previous['revision']+1 if previous else 1
            checkpoint = self.db.execute('SELECT COALESCE(max(id),0) FROM workspace_observations').fetchone()[0]
            # Edits start a new evaluation epoch. Existing observations remain
            # available to Preview but cannot be replayed into the live inbox.
            self.db.execute('''INSERT INTO workspace_rules
                (id,name,description,template,mode,enabled,priority,config_json,revision,checkpoint_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,description=excluded.description,template=excluded.template,
                mode=excluded.mode,enabled=excluded.enabled,priority=excluded.priority,
                config_json=excluded.config_json,revision=excluded.revision,checkpoint_id=excluded.checkpoint_id,
                condition_state='unknown',last_evaluated_at=NULL,last_successful_at=NULL,error=NULL,updated_at=excluded.updated_at''',
                (identity, value.name, value.description, value.template, value.mode, int(value.enabled), value.priority,
                 encode(value.config), revision, checkpoint, now, now))
            result = self.detail(identity)
            self.db.execute('INSERT INTO workspace_rule_revisions VALUES(?,?,?,?)',
                            (identity, revision, encode(result), now))
            return result

    def history(self, rule_id):
        with self.repo.lock:
            self.detail(rule_id)
            return {'items': [{'revision': row['revision'], 'at': row['at'], 'rule': json.loads(row['payload_json'])}
                              for row in self.db.execute('SELECT * FROM workspace_rule_revisions WHERE rule_id=? ORDER BY revision', (rule_id,))]}

    def preview(self, raw):
        from wici.tracking import MAX_AGE, timestamp
        from wici.workspace_monitor import _matches, evaluate, historical_observations
        value = RulePreview.model_validate(raw)
        with self.repo.lock:
            self._validate(value.rule)
            rule = value.rule.model_dump(mode='json')
            rule.update(id='preview', revision=0)
            area = self.workspace.areas.detail(rule['config']['area_id']) if rule['template'] == 'transport' else None
            observations, limited = historical_observations(self.workspace, rule, value.start, value.end)
            states, hits, gaps, matched = {}, [], 0, 0
            coverage_gaps = []
            last_observed = value.start
            transport_kind = (rule['config'].get('object_type') or
                              (rule['config'].get('object_ref') or 'ship:').split(':')[0])
            expected = (MAX_AGE[transport_kind] if rule['template'] == 'transport'
                        else 60 if rule['template'] == 'ukraine' else 7200)
            for observation in observations:
                ref = observation['object_ref']
                if not _matches(rule, observation):
                    continue
                matched += 1
                observed = timestamp(observation['observed_at'])
                if (observed-last_observed).total_seconds() > expected:
                    coverage_gaps.append({'from': iso(last_observed), 'to': iso(observed), 'reason': 'Brak zachowanych odczytów'})
                last_observed = observed
                if observation['kind'] == 'gap' and _matches(rule, observation):
                    if ref == '*':
                        states.clear()
                    else:
                        states.pop(ref, None)
                state, result = evaluate(rule, observation, states.get(ref), area)
                if state is None:
                    continue
                states[ref] = state
                if state['condition_state'] == 'unknown':
                    gaps += 1
                if result:
                    hits.append(dict(result, observation=observation, area=area,
                                     observed_at=observation['observed_at'], object_ref=ref))
            if not matched or (value.end-last_observed).total_seconds() > expected:
                coverage_gaps.append({'from': iso(last_observed), 'to': iso(value.end), 'reason': 'Brak zachowanych odczytów'})
            return {'items': hits[:500], 'dry_run': True, 'coverage': {
                'from': iso(value.start), 'to': iso(value.end), 'observations': matched,
                'gaps': gaps+len(coverage_gaps), 'unknown_intervals': coverage_gaps[:100],
                'limited': limited or len(hits) > 500 or len(coverage_gaps) > 100,
                'message': 'Wyłącznie zachowane odczyty lokalne. Brak odczytów i przerwy nie potwierdzają braku zdarzeń.'}}
