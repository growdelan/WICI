'use strict';
window.WiciReplayOrthophoto = (() => {
  const CLOSE_HEIGHT = 8000, FAR_HEIGHT = 10000;
  const FIRST_ZOOM = 11, LAST_ZOOM = 19, CONCURRENCY = 4, STARTS_PER_MINUTE = 180;
  const CACHE_SIZE = 96; // At most 24 MiB of decoded 256×256 RGBA pixels per open viewer.

  function attach(C, viewer, {enabled, emptyTile, decode, report}) {
    report('local');
    if (!enabled) return () => {};
    const rectangle = C.Rectangle.fromDegrees(13.8,48.8,24.4,55);
    const scheme = new C.WebMercatorTilingScheme();
    const credit = new C.Credit('Ortofotomapa · GUGiK / Geoportal');
    const photos = new Map();
    // Cesium's TileImagery uses a ready ancestor when a child's texture is
    // discarded. A real transparent tile still exposes ESA at coverage edges.
    const missing = document.createElement('canvas');
    missing.width = missing.height = 1;
    const discardMissing = {isReady:() => true, shouldDiscardImage:image => image === missing};
    const listeners = new AbortController();
    let batch = null, retained = null, retryAt = 0, serviceRetryAt = 0, retryTimer = 0, wakeTimer = 0, redraw = 0, disposed = false;
    let nextReport = 0, reported = 'local';
    const starts = [];
    const camera = viewer.camera, scene = viewer.scene;

    function status(value) {
      if (value !== reported) {reported = value; report(value);}
    }
    function updateCaption(group) {
      // Only describe tiles intersecting the current camera footprint. A missing
      // tile elsewhere along a long recording should not label this view incomplete.
      nextReport = performance.now() + 250;
      if (!group.dirty && C.Matrix4.equals(group.matrix,camera.viewMatrix)) return;
      group.dirty = false;
      group.matrix = C.Matrix4.clone(camera.viewMatrix,group.matrix);
      const footprint = camera.computeViewRectangle();
      let showing = false, gaps = false;
      if (footprint) for (const outcome of group.outcomes.values()) {
        if (!outcome.coverage || !C.Rectangle.simpleIntersection(footprint,outcome.bounds)) continue;
        if (outcome.coverage !== 'empty') showing = true;
        if (outcome.coverage !== 'full') gaps = true;
        if (showing && gaps) break;
      }
      if (retained && footprint && !showing) for (const outcome of retained.outcomes.values()) {
        if ((outcome.coverage === 'full' || outcome.coverage === 'partial') && C.Rectangle.simpleIntersection(footprint,outcome.bounds)) {
          showing = true; break;
        }
      }
      if (Date.now() < retryAt) gaps = true;
      if (showing) status(gaps ? 'partial' : 'orthophoto');
      else if (gaps) status('unavailable');
      else status(group.pending.size ? 'loading' : 'local');
    }
    function detach(keepVisible = false) {
      if (!batch && !retained) return;
      clearTimeout(wakeTimer); wakeTimer = 0;
      if (batch) {
        const group = batch; batch = null;
        for (const request of group.pending) request.abort();
        if (keepVisible && !retained && group.hasPhoto) retained = group;
        else viewer.imageryLayers.remove(group.layer,true);
        scene.requestRender();
      }
      if (retained && !keepVisible) {
        viewer.imageryLayers.remove(retained.layer,true); retained = null;
        scene.requestRender();
      }
    }
    function wakeAfterHit() {
      // A decoded image bypasses Cesium's network scheduler, including its
      // requestCompletedEvent. Wake a stationary camera after the promise settles.
      if (!redraw) redraw = requestAnimationFrame(() => {
        redraw = 0;
        if (batch && !disposed) scene.requestRender();
      });
    }
    function backoff(seconds, fromService = false) {
      const delay = Math.max(2, Math.min(3600, Number.isFinite(seconds) ? seconds : 30)) * 1000;
      const until = Date.now() + delay;
      if (fromService) serviceRetryAt = Math.max(serviceRetryAt,until);
      if (retryAt >= until) return;
      retryAt = until;
      clearTimeout(retryTimer);
      retryTimer = setTimeout(() => {
        retryAt = serviceRetryAt = 0;
        // Cesium retains INVALID imagery. Refresh it while the old, working
        // textures remain underneath until the replacement has reached the GPU.
        if (batch && wanted(batch)) {detach(true); add();}
        sync();
      },delay);
    }
    function coverage(group, image, blob) {
      if (blob.type !== 'image/png') return 'full';
      // The WMTS uses RGBA for tiles crossing the edge of its coverage,
      // including fully transparent tiles. Their gaps expose the ESA layer.
      if (!group.mask) {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 256;
        group.mask = canvas.getContext('2d',{willReadFrequently:true});
      }
      const mask = group.mask;
      if (!mask) return 'full';
      mask.globalCompositeOperation = 'copy';
      mask.drawImage(image,0,0);
      const pixels = mask.getImageData(0,0,256,256).data;
      let photo = false, gap = false;
      for (let i = 3; i < pixels.length; i += 4) {
        if (pixels[i]) photo = true;
        if (pixels[i] < 255) gap = true;
        if (photo && gap) return 'partial';
      }
      return photo ? 'full' : 'empty';
    }
    function trackTile(group, key, bounds, coverage) {
      const outcome = {bounds,coverage,credits:coverage && coverage !== 'empty' ? [credit] : []};
      if (coverage) group.accepted = true;
      if (outcome.credits.length) group.hasPhoto = true;
      group.outcomes.set(key,outcome);
      if (group.outcomes.size > 512) group.outcomes.delete(group.outcomes.keys().next().value);
      group.dirty = true; nextReport = 0;
      return outcome;
    }
    async function download(group, key, bounds) {
      const request = new AbortController();
      const outcome = trackTile(group,key,bounds,null);
      group.pending.add(request);
      const timer = setTimeout(() => request.abort(),18000);
      try {
        const response = await fetch('/api/flight-replay/orthophoto/' + key + '.jpg',{signal:request.signal});
        if (response.status === 404 || response.status === 204) {
          outcome.coverage = 'empty'; group.accepted = true;
          return emptyTile;
        }
        if (!response.ok) {
          if (response.status === 429 || response.status >= 500) {
            const header = response.headers.get('Retry-After');
            if (batch === group) backoff(header ? Number(header) : 30,true);
          }
          throw Error('Brak zdjęcia');
        }
        // GUGiK can return a PNG with transparent sea pixels at the coast,
        // even for a .jpg tile. Retain the image's native alpha channel.
        const blob = await response.blob(), image = await decode(blob);
        if (batch !== group) return emptyTile;
        outcome.coverage = coverage(group,image,blob);
        group.accepted = true;
        if (outcome.coverage !== 'empty') {outcome.credits.push(credit); group.hasPhoto = true;}
        const tile = {image:outcome.coverage === 'empty' ? emptyTile : image, coverage:outcome.coverage};
        photos.set(key,tile);
        if (photos.size > CACHE_SIZE) photos.delete(photos.keys().next().value);
        return tile.image;
      } catch (error) {
        if (batch === group) {
          if (error instanceof TypeError || error.name === 'AbortError') backoff(30);
          outcome.coverage = 'empty';
        }
        return missing;
      } finally {
        clearTimeout(timer); group.pending.delete(request);
        if (batch === group) {group.dirty = true; nextReport = 0; scene.requestRender();}
      }
    }
    function wanted(group) {
      return !document.hidden && navigator.onLine !== false && camera.positionCartographic.height < FAR_HEIGHT && batch === group;
    }
    function add() {
      const group = batch = {pending:new Set(), outcomes:new Map(),layer:null,dirty:true,matrix:null,hasPhoto:false,accepted:false};
      const provider = {
        tilingScheme:scheme,rectangle,minimumLevel:FIRST_ZOOM,maximumLevel:LAST_ZOOM,
        tileWidth:256,tileHeight:256,hasAlphaChannel:true,errorEvent:new C.Event(),tileDiscardPolicy:discardMissing,
        getTileCredits(x,y,level) {return group.outcomes.get(level + '/' + x + '/' + y)?.credits;},
        requestImage(x,y,level) {
          // During error recovery Cesium can also walk the imagery parent
          // chain below the WMTS range. No network call is needed there.
          if (level < FIRST_ZOOM) return Promise.resolve(emptyTile);
          if (retained === group) return Promise.resolve(missing);
          if (!wanted(group)) return Promise.resolve(emptyTile);
          const bounds = scheme.tileXYToRectangle(x,y,level);
          if (!C.Rectangle.simpleIntersection(rectangle,bounds)) return Promise.resolve(emptyTile);
          const key = level + '/' + x + '/' + y, cached = photos.get(key);
          if (cached) {
            photos.delete(key); photos.set(key,cached);
            trackTile(group,key,bounds,cached.coverage);
            wakeAfterHit();
            return Promise.resolve(cached.image);
          }
          if (Date.now() < retryAt) return Promise.resolve(missing);
          if (group.pending.size >= CONCURRENCY) return undefined;
          const now = Date.now();
          while (starts.length && starts[0] + 60000 <= now) starts.shift();
          if (starts.length >= STARTS_PER_MINUTE) {
            if (!wakeTimer) wakeTimer = setTimeout(() => {wakeTimer = 0; scene.requestRender();}, starts[0] + 60001 - now);
            return undefined;
          }
          starts.push(now);
          return download(group,key,bounds);
        }
      };
      // Restrict z11 imagery to already-refined terrain. Asking a world-level
      // terrain tile for every z11 tile covering Poland would allocate thousands
      // of textures. A level-9 terrain tile only overlaps a few orthophotos here.
      group.layer = new C.ImageryLayer(provider,{minimumTerrainLevel:9});
      viewer.imageryLayers.add(group.layer,retained ? 3 : 2);
      nextReport = 0; scene.requestRender();
    }
    function sync() {
      if (disposed) return;
      const height = camera.positionCartographic.height;
      if (navigator.onLine === false || document.hidden || height >= FAR_HEIGHT) {
        detach(); status(navigator.onLine === false ? 'offline' : 'local'); return;
      }
      if (!batch && height <= CLOSE_HEIGHT) add();
      if (batch && performance.now() >= nextReport) updateCaption(batch);
    }
    function networkChange() {
      if (Date.now() >= serviceRetryAt) {clearTimeout(retryTimer); retryAt = 0;}
      detach(); sync(); scene.requestRender();
    }
    const removeUpdate = scene.preUpdate.addEventListener(sync);
    const removeRender = scene.postRender.addEventListener(() => {
      if (!retained || !batch?.accepted || batch.pending.size || !scene.globe.tilesLoaded) return;
      viewer.imageryLayers.remove(retained.layer,true); retained = null;
      batch.dirty = true; nextReport = 0; scene.requestRender();
    });
    window.addEventListener('online',networkChange,{signal:listeners.signal});
    window.addEventListener('offline',networkChange,{signal:listeners.signal});
    document.addEventListener('visibilitychange',sync,{signal:listeners.signal});
    sync();
    return () => {
      disposed = true; clearTimeout(retryTimer); cancelAnimationFrame(redraw);
      removeUpdate(); removeRender(); listeners.abort(); detach(); photos.clear();
    };
  }
  return {attach};
})();
