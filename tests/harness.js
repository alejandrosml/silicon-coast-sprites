// harness.js - rendu WebGL (SwiftShader) de scenes simulees du moteur, avec les shaders donnes.
// Usage : node harness.js jobs.json   ; chaque job ecrit <out>.rgba (W*H*4, haut en premier).
// Les qualificatifs de precision sont retires (sur Mac, le moteur les definit a vide).
const { chromium } = require('playwright');
const fs = require('fs');
// WebGL (GLSL ES 1.00) impose des boucles a bornes constantes : on adapte la seule tournure
// du FPSELECT d'origine qui ne s'y plie pas (le source Mac reste inchange).
const webglize = s => s.replace(/\bint\s+x\s*,\s*y\s*;/g, '')
  .replace(/\bint\s+kSize\s*=\s*3\s*;/g, 'const int kSize = 3;')
  .replace(/for\s*\(\s*x\s*=\s*-kSize/g, 'for (int x = -kSize').replace(/for\s*\(\s*y\s*=\s*-kSize/g, 'for (int y = -kSize');
const strip = s => webglize(s.replace(/\b(lowp|mediump|highp)\b/g, ''));
const prefixFS = '#extension GL_OES_standard_derivatives : enable\nprecision highp float;\n';
const prefixVS = 'precision highp float;\n';
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cacheSrc = {};
const src = p => (cacheSrc[p] = cacheSrc[p] || strip(fs.readFileSync(p, 'utf8')));
const b64 = p => fs.readFileSync(p).toString('base64');

(async () => {
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  let page = await browser.newPage();
  page.on('console', m => console.log('[page]', m.text()));
  let count = 0;
  for (const job of spec.jobs) {
    if (++count % 40 === 0) {           // page neuve de temps en temps (memoire de SwiftShader)
      await page.close(); page = await browser.newPage();
      page.on('console', m => console.log('[page]', m.text()));
    }
    const payload = {
      W: job.width || spec.width, H: job.height || spec.height,
      vs: prefixVS + src(job.vs), fs: prefixFS + src(job.fs),
      pages: (job.pages || [{ atlas: job.atlas, verts: job.verts }]).map(p => ({ atlas: b64(p.atlas), verts: b64(p.verts) })),
      atlasW: job.atlasW || 1024, atlasH: job.atlasH || 1024,
      filter: job.filter || 'linear',
      uniforms: job.uniforms || {}, clear: job.clear || [0, 0, 0, 0],
      bg: job.bg ? b64(job.bg) : null, blend: job.blend || [0x0302, 0x0303],
    };
    const res = await page.evaluate((P) => {
      const dec = s => { const b = atob(s); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };
      const c = document.createElement('canvas'); c.width = P.W; c.height = P.H;
      const gl = c.getContext('webgl', { premultipliedAlpha: false, preserveDrawingBuffer: true, antialias: false, alpha: true });
      if (!gl) return { err: 'no webgl' };
      gl.getExtension('OES_standard_derivatives');
      const mk = (t, s) => { const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh); if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error((t === gl.VERTEX_SHADER ? 'VS: ' : 'FS: ') + gl.getShaderInfoLog(sh)); return sh; };
      let pr;
      try {
        pr = gl.createProgram(); gl.attachShader(pr, mk(gl.VERTEX_SHADER, P.vs)); gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, P.fs));
        gl.bindAttribLocation(pr, 0, 'aPos'); gl.bindAttribLocation(pr, 1, 'aTc'); gl.bindAttribLocation(pr, 2, 'aColor'); gl.bindAttribLocation(pr, 3, 'aRef');
        gl.linkProgram(pr);
        if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) throw new Error('LINK: ' + gl.getProgramInfoLog(pr));
      } catch (e) { return { err: String(e.message || e) }; }
      gl.useProgram(pr);
      // fond eventuel : texture plein ecran dessinee avec un programme simple
      gl.viewport(0, 0, P.W, P.H);
      gl.clearColor(P.clear[0], P.clear[1], P.clear[2], P.clear[3]); gl.clear(gl.COLOR_BUFFER_BIT);
      if (P.bg) {
        const bvs = 'attribute vec2 p; varying vec2 t; void main(){ t = p*0.5+0.5; t.y = 1.0 - t.y; gl_Position = vec4(p,0.0,1.0); }';
        const bfs = 'precision highp float; uniform sampler2D s; varying vec2 t; void main(){ gl_FragColor = texture2D(s, t); }';
        const bp = gl.createProgram(); gl.attachShader(bp, mk(gl.VERTEX_SHADER, bvs)); gl.attachShader(bp, mk(gl.FRAGMENT_SHADER, bfs)); gl.linkProgram(bp); gl.useProgram(bp);
        const bt = gl.createTexture(); gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, bt);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, P.W, P.H, 0, gl.RGBA, gl.UNSIGNED_BYTE, dec(P.bg));
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.uniform1i(gl.getUniformLocation(bp, 's'), 1);
        const bb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const l = gl.getAttribLocation(bp, 'p'); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.disableVertexAttribArray(l);
        gl.useProgram(pr); gl.activeTexture(gl.TEXTURE0);
      }
      const U = (n) => gl.getUniformLocation(pr, n);
      if (U('uTex')) gl.uniform1i(U('uTex'), 0);
      if (U('uTcScale')) gl.uniform2f(U('uTcScale'), 1 / P.atlasW, 1 / P.atlasH);
      for (const [k, v] of Object.entries(P.uniforms)) {
        const l = U(k); if (!l) continue;
        if (typeof v === 'number') gl.uniform1f(l, v);
        else if (v.length === 2) gl.uniform2f(l, v[0], v[1]);
        else if (v.length === 3) gl.uniform3f(l, v[0], v[1], v[2]);
        else gl.uniform4f(l, v[0], v[1], v[2], v[3]);
      }
      // une page par vidage de la file de dessin du moteur (atlas plein) : meme image, atlas neuf
      const F = P.filter === 'nearest' ? gl.NEAREST : gl.LINEAR;
      gl.enable(gl.BLEND); gl.blendFunc(P.blend[0], P.blend[1]);
      const at = (i, n, off) => { gl.enableVertexAttribArray(i); gl.vertexAttribPointer(i, n, gl.FLOAT, false, 40, off * 4); };
      let tex = null, buf = null;
      for (const pg of P.pages) {
        tex = gl.createTexture(); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, P.atlasW, P.atlasH, 0, gl.RGBA, gl.UNSIGNED_BYTE, dec(pg.atlas));
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, F); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, F);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        const vb = dec(pg.verts); const fv = new Float32Array(vb.buffer, vb.byteOffset, vb.byteLength / 4);
        buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, fv, gl.STATIC_DRAW);
        at(0, 2, 0); at(1, 2, 2); at(2, 4, 4); at(3, 2, 8);
        gl.drawArrays(gl.TRIANGLES, 0, fv.length / 10);
        gl.deleteTexture(tex); gl.deleteBuffer(buf); tex = null; buf = null;
      }
      const px = new Uint8Array(P.W * P.H * 4); gl.readPixels(0, 0, P.W, P.H, gl.RGBA, gl.UNSIGNED_BYTE, px);
      const img = new Uint8Array(P.W * P.H * 4);
      for (let y = 0; y < P.H; y++) img.set(px.subarray((P.H - 1 - y) * P.W * 4, (P.H - y) * P.W * 4), y * P.W * 4);
      let s = ''; for (let i = 0; i < img.length; i += 32768) s += String.fromCharCode.apply(null, img.subarray(i, i + 32768));
      // liberer le contexte : sinon les contextes s'accumulent et le moteur de rendu finit par planter
      gl.deleteProgram(pr);
      const lose = gl.getExtension('WEBGL_lose_context'); if (lose) lose.loseContext();
      c.width = 1; c.height = 1;
      return { data: btoa(s) };
    }, payload);
    if (res.err) { console.log('ERR', job.out, res.err); fs.writeFileSync(job.out + '.err', res.err); continue; }
    fs.writeFileSync(job.out + '.rgba', Buffer.from(res.data, 'base64'));
    console.log('ok', job.out);
  }
  await browser.close();
})().catch(e => { console.error('ERR', e); process.exit(1); });
