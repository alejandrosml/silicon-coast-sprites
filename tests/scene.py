# scene.py - fabrique des scenes simulees (atlas + sommets) et les rend dans WebGL via harness.js
import os, json, subprocess, hashlib
import numpy as np
from engine_sim import Atlas, realize_palette, render_creature, pack

D = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(D, 'work')
os.makedirs(WORK, exist_ok=True)
HARNESS = os.path.join(os.path.dirname(D), 'gltest', 'harness.js')
ORIG = os.path.join(D, 'orig')
NEW = os.path.join(D, 'shaders_out')

def ust(z, cam, W, H):
    return [2.0 * z / W, -2.0 * z / H, -1.0 - 2.0 * z * cam[0] / W, 1.0 + 2.0 * z * cam[1] / H]

class Job:
    def __init__(self, name, atlas_img, verts, z, cam, W, H, filt='linear', fs='FPDRAW', vs='VPDRAW',
                 shaders='new', tone=(0, 0, 0, 0), blur=5.0):
        if isinstance(atlas_img, list):         # pages [(atlas, sommets), ...] (atlas plein -> vidage)
            self.pages = atlas_img
        else:
            self.pages = [(atlas_img, verts)]
        self.name, self.atlas = name, self.pages[0][0]
        self.verts = [v for p in self.pages for v in p[1]]
        self.z, self.cam, self.W, self.H, self.filt = z, cam, W, H, filt
        self.fs, self.vs, self.shaders, self.tone, self.blur = fs, vs, shaders, tone, blur

def run_jobs(jobs, tag='batch'):
    """rend chaque job sur fond noir et blanc ; renvoie {name: (rgb_premult float, alpha float)}"""
    spec = {'jobs': []}
    files = {}
    for j in jobs:
        pages = []
        for pi, (img, vv) in enumerate(j.pages):
            h = hashlib.md5(img.tobytes()).hexdigest()[:12]
            ap = os.path.join(WORK, f'atlas_{h}.rgba')
            if not os.path.exists(ap):
                img.tofile(ap)
            vp = os.path.join(WORK, f'{tag}_{j.name}_p{pi}.f32')
            np.asarray(pack(vv), np.float32).tofile(vp)
            pages.append(dict(atlas=ap, verts=vp))
        ap, vp = pages[0]['atlas'], pages[0]['verts']
        sd = NEW if j.shaders == 'new' else ORIG
        for bgname, clear in (('k', [0, 0, 0, 1]), ('w', [1, 1, 1, 1])):
            out = os.path.join(WORK, f'{tag}_{j.name}_{bgname}')
            for ext in ('.err', '.rgba'):
                if os.path.exists(out + ext):
                    os.remove(out + ext)
            spec['jobs'].append(dict(out=out, vs=os.path.join(sd, j.vs + '.GLSL'), fs=os.path.join(sd, j.fs + '.GLSL'),
                                     atlas=ap, filter=j.filt, verts=vp, pages=pages, width=j.W, height=j.H, clear=clear,
                                     uniforms={'uST': ust(j.z, j.cam, j.W, j.H), 'uColorTone': list(j.tone),
                                               'uSpriteBlurAmount': j.blur}))
            files[(j.name, bgname)] = out
    sp = os.path.join(WORK, f'{tag}.json')
    json.dump(spec, open(sp, 'w'))
    r = subprocess.run(['node', HARNESS, sp], capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
    res = {}
    for j in jobs:
        ok = True
        imgs = {}
        for bg in ('k', 'w'):
            p = files[(j.name, bg)]
            if os.path.exists(p + '.err'):
                raise RuntimeError(j.name + ': ' + open(p + '.err').read())
            imgs[bg] = np.fromfile(p + '.rgba', np.uint8).reshape(j.H, j.W, 4)[..., :3].astype(np.float64) / 255.0
        a = 1.0 - (imgs['w'] - imgs['k']).mean(axis=2)
        res[j.name] = dict(prem=imgs['k'], alpha=np.clip(a, 0, 1), black=imgs['k'], white=imgs['w'])
    return res

def to_png(path, rgb):
    from PIL import Image
    Image.fromarray(np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)).save(path)
