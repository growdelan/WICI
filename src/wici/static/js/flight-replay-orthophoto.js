'use strict';
window.WiciReplayOrthophoto = (() => {
  const CLOSE_HEIGHT = 8000, FAR_HEIGHT = 10000;
  const FIRST_ZOOM = 11, LAST_ZOOM = 19, CONCURRENCY = 2, STARTS_PER_MINUTE = 180;

  function attach(C, viewer, {enabled, emptyTile, decode, report}) {
    report('local');
    if (!enabled) return () => {};
    const rectangle = C.Rectangle.fromDegrees(13.8,48.8,24.4,55);
    const scheme = new C.WebMercatorTilingScheme();
    const credit = new C.Credit('Ortofotomapa · GUGiK / Geoportal');
    const listeners = new AbortController();
    let batch = null, retryAt = 0, serviceRetryAt = 0, retryTimer = 0, wakeTimer = 0, disposed = false;
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
      let photos = false, gaps = false;
      if (footprint) for (const outcome of group.outcomes.values()) {
        if (!outcome.coverage || !C.Rectangle.simpleIntersection(footprint,outcome.bounds)) continue;
        if (outcome.coverage !== 'empty') photos = true;
        if (outcome.coverage !== 'full') gaps = true;
        if (photos && gaps) break;
      }
      if (Date.now() < retryAt) gaps = true;
      if (photos) status(gaps ? 'partial' : 'orthophoto');
      else if (gaps) status('unavailable');
      else status(group.pending.size ? 'loading' : 'local');
    }
    function detach() {
      if (!batch) return;
      const group = batch; batch = null;
      clearTimeout(wakeTimer); wakeTimer = 0;
      for (const request of group.pending) request.abort();
      viewer.imageryLayers.remove(group.layer,true);
      scene.requestRender();
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
        // Transparent substitutes are cached by Cesium. A fresh layer also
        // retries them after the provider recovers, without reopening the dialog.
        detach(); sync();
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
    async function download(group, x, y, level, bounds) {
      const request = new AbortController(), key = level + '/' + x + '/' + y;
      const outcome = {bounds,coverage:null,credits:[]};
      group.outcomes.set(key,outcome);
      if (group.outcomes.size > 512) group.outcomes.delete(group.outcomes.keys().next().value);
      group.pending.add(request); group.dirty = true; nextReport = 0;
      const timer = setTimeout(() => request.abort(),18000);
      try {
        const response = await fetch('/api/flight-replay/orthophoto/' + key + '.jpg',{signal:request.signal});
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
        if (outcome.coverage !== 'empty') outcome.credits.push(credit);
        return image;
      } catch (error) {
        if (batch === group) {
          if (error instanceof TypeError || error.name === 'AbortError') backoff(30);
          outcome.coverage = 'empty';
        }
        return emptyTile;
      } finally {
        clearTimeout(timer); group.pending.delete(request);
        if (batch === group) {group.dirty = true; nextReport = 0; scene.requestRender();}
      }
    }
    function wanted(group) {
      return !document.hidden && navigator.onLine !== false && camera.positionCartographic.height < FAR_HEIGHT && batch === group;
    }
    function add() {
      const group = batch = {pending:new Set(), outcomes:new Map(),layer:null,dirty:true,matrix:null};
      const provider = {
        tilingScheme:scheme,rectangle,minimumLevel:0,maximumLevel:LAST_ZOOM,
        tileWidth:256,tileHeight:256,hasAlphaChannel:true,errorEvent:new C.Event(),
        getTileCredits(x,y,level) {return group.outcomes.get(level + '/' + x + '/' + y)?.credits;},
        requestImage(x,y,level) {
          // Starting the provider at z11 across Poland would create thousands
          // of level-zero imagery tiles. Lower quadtree levels are local blanks.
          if (level < FIRST_ZOOM || !wanted(group) || Date.now() < retryAt) return Promise.resolve(emptyTile);
          if (group.pending.size >= CONCURRENCY) return undefined;
          const bounds = scheme.tileXYToRectangle(x,y,level);
          if (!C.Rectangle.simpleIntersection(rectangle,bounds)) return Promise.resolve(emptyTile);
          const now = Date.now();
          while (starts.length && starts[0] + 60000 <= now) starts.shift();
          if (starts.length >= STARTS_PER_MINUTE) {
            if (!wakeTimer) wakeTimer = setTimeout(() => {wakeTimer = 0; scene.requestRender();}, starts[0] + 60001 - now);
            return undefined;
          }
          starts.push(now);
          return download(group,x,y,level,bounds);
        }
      };
      // Natural Earth and ESA are the first two layers; radar is always above imagery.
      group.layer = viewer.imageryLayers.addImageryProvider(provider,2);
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
    window.addEventListener('online',networkChange,{signal:listeners.signal});
    window.addEventListener('offline',networkChange,{signal:listeners.signal});
    document.addEventListener('visibilitychange',sync,{signal:listeners.signal});
    sync();
    return () => {
      disposed = true; clearTimeout(retryTimer); removeUpdate(); listeners.abort(); detach();
    };
  }
  return {attach};
})();
