'use strict';
// Reconstructed paths are straight chords in the Earth-fixed frame. The dim
// catalogue strokes remain selectable when the meteor itself is no longer visible.
window.WiciMeteorScene = (() => {
  const CITIES = [
    ['Szczecin',14.553,53.429], ['Gdańsk',18.647,54.352], ['Poznań',16.925,52.406],
    ['Warszawa',21.012,52.230], ['Wrocław',17.039,51.108], ['Kraków',19.945,50.065],
    ['Lublin',22.568,51.247], ['Białystok',23.169,53.133]
  ];
  const AFTERGLOW_SECONDS = 180;
  function glowSprite() {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 64;
    const ctx = canvas.getContext('2d');
    const glow = ctx.createRadialGradient(32,32,0,32,32,32);
    glow.addColorStop(0,'rgba(255,255,244,1)');
    glow.addColorStop(.10,'rgba(255,251,220,.95)');
    glow.addColorStop(.25,'rgba(255,222,143,.57)');
    glow.addColorStop(.52,'rgba(255,175,97,.16)');
    glow.addColorStop(1,'rgba(255,175,97,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0,0,64,64);
    return canvas;
  }

  function create(container, C, {onPick = () => {}, onError = () => {}} = {}) {
    // Use packaged module workers, as in WiciFlightReplay, under WICI's CSP.
    window.CESIUM_WORKERS = undefined;
    const viewer = new C.Viewer(container, {
      animation:false, timeline:false, geocoder:false, baseLayerPicker:false, homeButton:false,
      navigationHelpButton:false, fullscreenButton:false, vrButton:false, infoBox:false,
      sceneModePicker:false, selectionIndicator:false, scene3DOnly:true, baseLayer:false,
      shouldAnimate:false, requestRenderMode:true, maximumRenderTimeChange:Infinity,
      terrainProvider:new C.EllipsoidTerrainProvider(), showRenderLoopErrors:false
    });
    const {scene, camera} = viewer;
    const abort = new AbortController();
    const horizonNote = document.createElement('p');
    horizonNote.className = 'meteor-horizon-note';
    horizonNote.textContent = 'Ta trajektoria znajduje się poniżej horyzontu wybranego obserwatora.';
    horizonNote.hidden = true;
    container.append(horizonNote);
    const color = C.Color.fromCssColorString;
    const xyz = (p, h = p.alt_km * 1000) => C.Cartesian3.fromDegrees(p.lon,p.lat,h);
    const cityEntities = [], horizonMarks = [], skyGuides = [], witnesses = [], tracks = new Map(), picked = new Map();
    let mode = 'night', selected, observer, sight, time = NaN, dead = false, failed = false;
    let border, resize, removeError;
    const reportError = () => {
      if (dead || failed) return;
      failed = true;
      queueMicrotask(() => { if (!dead) onError('Utracono obraz 3D. Zamknij widok i otwórz go ponownie.'); });
    };
    const entity = options => viewer.entities.add(options);
    const stroke = (positions, width, material) => ({positions, width, material, arcType:C.ArcType.NONE});
    const dark = color('#0a1223'), pearl = color('#f7edd2'), gold = color('#ffc775');
    const traceInk = color('#91aeb6').withAlpha(.61), recentInk = color('#f0b36c');
    const glowMaterial = new C.PolylineGlowMaterialProperty({color:gold, glowPower:.23, taperPower:.45});
    function textMark(text, fill, offset = -8) {
      return {text, font:'12px system-ui, sans-serif', fillColor:fill, outlineColor:dark, outlineWidth:3,
        style:C.LabelStyle.FILL_AND_OUTLINE, verticalOrigin:C.VerticalOrigin.BOTTOM,
        pixelOffset:new C.Cartesian2(0,offset)};
    }
    function imagery(url, options, brightness, saturation) {
      const layer = viewer.imageryLayers.addImageryProvider(new C.UrlTemplateImageryProvider({url,...options}));
      layer.brightness = brightness;
      layer.saturation = saturation;
      return layer;
    }
    async function addBorder() {
      try {
        const response = await fetch('/static/geo/poland-border.geojson',{signal:abort.signal});
        if (!response.ok) return;
        const {geometry} = await response.json();
        if (dead || failed || geometry.type !== 'LineString') return;
        const positions = geometry.coordinates.map(([lon,lat]) => C.Cartesian3.fromDegrees(lon,lat,160));
        border = entity({id:'meteor-poland-border', show:mode !== 'ground',
          polyline:stroke(positions,1.4,color('#92bfca').withAlpha(.75))});
        scene.requestRender();
      } catch { /* Map labels and imagery remain usable if the local border is missing. */ }
    }
    function destroy() {
      if (dead) return;
      dead = true;
      abort.abort();
      horizonNote.remove();
      resize?.disconnect();
      removeError?.();
      viewer.canvas.removeEventListener('webglcontextlost',reportError);
      try { if (!viewer.isDestroyed()) viewer.destroy(); } catch { /* Context already lost. */ }
      tracks.clear(); picked.clear();
    }

    const flyers = [];
    let sprite, focusLine, groundLine, observerDot;
    function addFlyer() {
      const suffix = flyers.length ? '-' + (flyers.length + 1) : '';
      const head = entity({id:'meteor-head'+suffix,show:false,point:{pixelSize:5,color:C.Color.WHITE},
        billboard:{image:sprite,width:38,height:38}});
      const tail = entity({id:'meteor-tail'+suffix,show:false,polyline:stroke([],9,glowMaterial)});
      const flyer = {head,tail};
      flyers.push(flyer);
      return flyer;
    }
    try {
      viewer.resolutionScale = Math.min(1,1.65/(window.devicePixelRatio || 1));
      scene.backgroundColor = color('#050914');
      scene.globe.baseColor = color('#152337');
      scene.globe.enableLighting = false;
      scene.globe.depthTestAgainstTerrain = true;
      scene.globe.showGroundAtmosphere = false;
      if (scene.skyAtmosphere) {
        scene.skyAtmosphere.brightnessShift = -.65;
        scene.skyAtmosphere.saturationShift = -.22;
      }
      // Cool the dark terrain and horizon while retaining real image detail and
      // the warm luminous core. This is a display treatment of the daytime mosaic.
      scene.postProcessStages.add(new C.PostProcessStage({name:'meteor-night-tones',fragmentShader:`
        uniform sampler2D colorTexture;
        in vec2 v_textureCoordinates;
        void main() {
          vec4 pixel = texture(colorTexture, v_textureCoordinates);
          float value = dot(pixel.rgb, vec3(0.2126, 0.7152, 0.0722));
          float shadow = 1.0 - smoothstep(0.26, 0.63, max(max(pixel.r, pixel.g), pixel.b));
          vec3 night = vec3(0.016, 0.035, 0.070) + value * vec3(0.50, 0.76, 1.02)
                     + 0.22 * (pixel.rgb - vec3(value));
          out_FragColor = vec4(mix(pixel.rgb, night, shadow), pixel.a);
        }`}));
      // The packaged Tycho skybox follows the observation's UTC time. A subdued
      // local land mosaic supplies orientation, rather than simulated city lights.
      scene.fog.enabled = false;
      imagery('/static/vendor/cesium/Assets/Textures/NaturalEarthII/{z}/{x}/{reverseY}.jpg', {
        tilingScheme:new C.GeographicTilingScheme(), minimumLevel:0, maximumLevel:2,
        credit:new C.Credit('Natural Earth')}, .38, .33);
      const rectangle = C.Rectangle.fromDegrees(13,48,25,56);
      imagery('/static/geo/flight-satellite/{x}-{y}.webp',{
        rectangle, tilingScheme:new C.GeographicTilingScheme({rectangle,numberOfLevelZeroTilesX:6,numberOfLevelZeroTilesY:4}),
        minimumLevel:0, maximumLevel:0, tileWidth:1024, tileHeight:1024,
        credit:new C.Credit('© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium.')
      }, .52, .45);
      for (const [name,lon,lat] of CITIES) cityEntities.push(entity({
        position:C.Cartesian3.fromDegrees(lon,lat,260), point:{pixelSize:3,color:color('#c2d1cd')},
        label:textMark(name,color('#c2d1cd'))
      }));
      focusLine = entity({id:'meteor-reference',show:false,polyline:stroke([],2,
        new C.PolylineDashMaterialProperty({color:pearl.withAlpha(.60),dashLength:12}))});
      groundLine = entity({show:false,polyline:stroke([],1.5,color('#94b9c1').withAlpha(.65))});
      for (const name of ['Początek','Koniec']) witnesses.push(entity({show:false,
        polyline:stroke([],1.1,new C.PolylineDashMaterialProperty({color:color('#a8c9d8').withAlpha(.62),dashLength:8})),
        label:textMark(name,pearl,-11), point:{pixelSize:4,color:pearl}
      }));
      sprite = glowSprite();
      addFlyer();
      observerDot = entity({show:false,point:{pixelSize:6,color:color('#8fdfdf')},label:textMark('Obserwator',pearl)});
      for (const direction of ['N','NE','E','SE','S','SW','W','NW']) horizonMarks.push(entity({
        show:false,label:textMark(direction,color('#a5ccdb'),-4)
      }));
      for (const elevation of [0,30,60,75]) skyGuides.push(entity({
        show:false,polyline:stroke([],1,color('#91afca').withAlpha(elevation ? .20 : .44)),
        label:textMark(elevation+'°',color('#9db5c6'),-3)
      }));
      viewer.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
      viewer.screenSpaceEventHandler.setInputAction(click => {
        if (mode !== 'night' || dead) return;
        const exact = picked.get(scene.pick(click.position)?.id);
        if (exact !== undefined) { onPick(exact); return; }
        for (const hit of scene.drillPick(click.position,5,9,9)) {
          const id = picked.get(hit.id);
          if (id !== undefined) { onPick(id); break; }
        }
      },C.ScreenSpaceEventType.LEFT_CLICK);
      removeError = scene.renderError.addEventListener(reportError);
      viewer.canvas.addEventListener('webglcontextlost',reportError);
      addBorder();
    } catch (error) { destroy(); throw error; }

    const countryPoints = [[14.35,53.6],[14.8,50.9],[18.4,54.8],[23,54.2],[24.1,50.9],[22.7,49.0],[19,49.2]]
      .map(([lon,lat]) => C.Cartesian3.fromDegrees(lon,lat));
    function setNight(data) {
      if (dead) return;
      for (const record of tracks.values()) viewer.entities.remove(record.line);
      tracks.clear(); picked.clear();
      for (const event of data.events) {
        const start = xyz(event.begin), end = xyz(event.end);
        const line = entity({id:'meteor-path-'+event.id,name:event.id,position:end,
          point:{pixelSize:3.5,color:traceInk},polyline:stroke([start,end],2,traceInk)});
        tracks.set(event.id,{event,start,end,line,level:0});
        picked.set(line,event.id);
      }
      setView('night',null,null);
    }

    function fit(points, heading, pitch, minDistance) {
      const center = C.BoundingSphere.fromPoints(points).center;
      camera.lookAt(center,new C.HeadingPitchRange(heading,pitch,300000));
      const tanY = Math.tan(camera.frustum.fovy/2);
      const tanX = tanY * camera.frustum.aspectRatio;
      let distance = minDistance;
      for (const p of points) {
        const d = C.Cartesian3.subtract(p,center,new C.Cartesian3());
        const depth = C.Cartesian3.dot(d,camera.directionWC);
        distance = Math.max(distance,Math.abs(C.Cartesian3.dot(d,camera.rightWC))*1.10/tanX-depth,
          Math.abs(C.Cartesian3.dot(d,camera.upWC))*(mode === 'night' ? 1.10 : 1.24)/tanY-depth);
      }
      camera.lookAt(center,new C.HeadingPitchRange(heading,pitch,distance));
      camera.lookAtTransform(C.Matrix4.IDENTITY);
    }
    function aimFromObserver() {
      const eye = xyz(observer,2);
      const enu = C.Transforms.eastNorthUpToFixedFrame(eye);
      const inverse = C.Matrix4.inverseTransformation(enu,new C.Matrix4());
      const unit = point => C.Cartesian3.normalize(C.Matrix4.multiplyByPoint(inverse,point,new C.Cartesian3()),new C.Cartesian3());
      const first = unit(selected.start), last = unit(selected.end);
      const mid = unit(C.Cartesian3.midpoint(selected.start,selected.end,new C.Cartesian3()));
      const heading = Math.atan2(mid.x,mid.y), elevation = Math.asin(mid.z);
      const visible = Math.max(first.z,last.z) > 0;
      sight = {visible, azimuth_deg:(C.Math.toDegrees(heading)+360)%360, elevation_deg:C.Math.toDegrees(elevation), inverse};
      camera.setView({destination:eye,orientation:{heading,pitch:visible ? Math.max(.01,elevation) : .08,roll:0}});
      const halfSpan = 1.2*Math.max(C.Cartesian3.angleBetween(first,mid),C.Cartesian3.angleBetween(last,mid));
      const aspect = camera.frustum.aspectRatio;
      const fovForSpan = 2*Math.atan(Math.tan(halfSpan)*Math.max(aspect,1/aspect));
      camera.frustum.fov = C.Math.clamp(Math.max(C.Math.toRadians(57),fovForSpan),C.Math.toRadians(45),C.Math.toRadians(112));
      for (const [i,mark] of horizonMarks.entries()) {
        const angle = C.Math.TWO_PI*i/horizonMarks.length;
        const local = new C.Cartesian3(30000*Math.sin(angle),30000*Math.cos(angle),0);
        mark.position = C.Matrix4.multiplyByPoint(enu,local,new C.Cartesian3());
        mark.show = true;
      }
      // A local altitude circle remains meaningful when an overhead meteor puts
      // the physical horizon entirely outside the field of view.
      const onSky = (azimuth, height) => {
        const h = C.Math.toRadians(height), a = C.Math.toRadians(azimuth), r = 100000;
        const local = new C.Cartesian3(r*Math.sin(a)*Math.cos(h), r*Math.cos(a)*Math.cos(h), r*Math.sin(h));
        return C.Matrix4.multiplyByPoint(enu,local,new C.Cartesian3());
      };
      [0,30,60,75].forEach((height,i) => {
        const guide = skyGuides[i];
        guide.polyline.positions = Array.from({length:73},(_,n) => onSky(5*n,height));
        guide.position = onSky(sight.azimuth_deg+18,height);
        guide.show = true;
      });
    }
    function frameView() {
      if (dead || !container.clientWidth || !container.clientHeight) return;
      viewer.resize();
      camera.lookAtTransform(C.Matrix4.IDENTITY);
      camera.frustum.fov = C.Math.toRadians(60);
      camera.frustum.aspectRatio = viewer.canvas.clientWidth / Math.max(1,viewer.canvas.clientHeight);
      if (mode === 'night') {
        const points = countryPoints.slice();
        for (const {start,end} of tracks.values()) points.push(start,end);
        fit(points,C.Math.toRadians(4),C.Math.toRadians(-36),330000);
      } else if (mode === 'ground') {
        aimFromObserver();
      } else {
        // Broadside to the flight direction so its measured length and descent
        // are legible. Frame both the atmospheric endpoints and ground projections.
        const {event,start,end} = selected;
        const inverse = C.Matrix4.inverseTransformation(C.Transforms.eastNorthUpToFixedFrame(start),new C.Matrix4());
        const localEnd = C.Matrix4.multiplyByPoint(inverse,end,new C.Cartesian3());
        const broadside = Math.atan2(localEnd.x,localEnd.y)+Math.PI/2;
        fit([start,end,xyz(event.begin,0),xyz(event.end,0)],broadside,C.Math.toRadians(-18),64000);
      }
      scene.requestRender();
    }
    function setView(next, event, place) {
      if (dead) return;
      selected = event ? tracks.get(event.id) : null;
      mode = selected && (next === 'trajectory' || (next === 'ground' && place)) ? next : 'night';
      observer = place;
      sight = null;
      for (const record of tracks.values()) record.line.show = mode === 'night';
      for (const item of cityEntities) item.show = mode !== 'ground';
      for (const mark of horizonMarks) mark.show = false;
      for (const guide of skyGuides) guide.show = false;
      // Cesium's ground-level atmospheric scattering otherwise hides the
      // packaged Tycho skybox even at the historical nighttime UTC.
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = mode !== 'ground';
      if (border) border.show = mode !== 'ground';
      const detail = mode !== 'night', profile = mode === 'trajectory';
      focusLine.show = detail; groundLine.show = profile;
      for (const item of witnesses) item.show = profile;
      observerDot.show = profile && Boolean(place);
      if (observerDot.show) observerDot.position = xyz(place,40);
      if (detail) {
        const {start,end} = selected;
        focusLine.polyline.material.color = pearl.withAlpha(profile ? .60 : .29);
        focusLine.polyline.positions = [start,end];
        if (profile) {
          const feet = [xyz(event.begin,50),xyz(event.end,50)];
          groundLine.polyline.positions = feet;
          [event.begin,event.end].forEach((p,i) => {
            const witness = witnesses[i], top = i ? end : start;
            witness.position = top;
            witness.polyline.positions = [feet[i],top];
            witness.label.text = (i ? 'Koniec' : 'Początek')+' · '+Math.round(p.alt_km)+' km';
          });
        }
      }
      scene.screenSpaceCameraController.enableInputs = mode !== 'ground';
      frameView();
      if (sight && !sight.visible) focusLine.show = false;
      horizonNote.hidden = !sight || sight.visible;
      draw(time);
      return sight && {visible:sight.visible,azimuth_deg:sight.azimuth_deg,elevation_deg:sight.elevation_deg};
    }

    function paintFlyer(record, index, epoch) {
      const {event,start,end} = record;
      const {head,tail} = flyers[index] || addFlyer();
      const age = epoch-event.start, fraction = Math.min(1,age/event.duration);
      const position = C.Cartesian3.lerp(start,end,fraction,new C.Cartesian3());
      const visible = !sight || C.Matrix4.multiplyByPoint(sight.inverse,position,new C.Cartesian3()).z > 0;
      head.show = visible;
      tail.show = visible && age > 0;
      head.name = tail.name = event.id;
      if (mode === 'night') {
        picked.set(head,event.id); picked.set(tail,event.id);
      } else { picked.delete(head); picked.delete(tail); }
      if (!visible) return;
      head.position = position;
      // The glow marks a measured location. Its size is a display aid, not a diameter estimate.
      const mag = Number.isFinite(event.magnitude) ? event.magnitude : 1;
      const size = C.Math.clamp(38-mag*2,26,60);
      head.billboard.width = head.billboard.height = size;
      if (tail.show) {
        const before = Math.max(0,fraction-Math.min(.32,.22/event.duration));
        tail.polyline.positions = [C.Cartesian3.lerp(start,end,before,new C.Cartesian3()),position];
      }
    }
    function inFlight(event, epoch) {
      return event.duration > 0 && epoch >= event.start && epoch <= event.start+event.duration;
    }
    function draw(epoch) {
      if (dead || failed || !Number.isFinite(epoch)) return;
      time = epoch;
      viewer.clock.currentTime = C.JulianDate.fromDate(new Date(epoch*1000));
      let count = 0;
      if (mode === 'night') {
        for (const record of tracks.values()) {
          const age = epoch-record.event.start, duration = record.event.duration;
          const strength = age < 0 ? 0 : Math.max(0,1-Math.max(0,age-duration)/AFTERGLOW_SECONDS);
          const level = Math.ceil(strength*12);
          if (level !== record.level) {
            const tint = level ? C.Color.lerp(traceInk,recentInk,level/12,new C.Color()) : traceInk;
            record.line.polyline.material = tint;
            record.line.polyline.width = 2+2*level/12;
            record.line.point.color = tint;
            record.level = level;
          }
          if (inFlight(record.event,epoch)) paintFlyer(record,count++,epoch);
        }
      } else if (selected && inFlight(selected.event,epoch)) {
        paintFlyer(selected,count++,epoch);
      }
      // Share slots across time and both detail modes. Pool size depends only on
      // the maximum number of simultaneous meteors that have been drawn.
      for (let i=count; i<flyers.length; i++) {
        const {head,tail} = flyers[i];
        head.show = tail.show = false;
        picked.delete(head); picked.delete(tail);
      }
      scene.requestRender();
    }
    resize = new ResizeObserver(frameView);
    resize.observe(container);
    return {setNight,setView,draw,destroy};
  }
  return {create};
})();
