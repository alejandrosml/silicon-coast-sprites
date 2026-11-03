# bl_game.py - Silicon Coast : rendu Blender a la camera de BG2:EE (orthographique, 39 degres, 8 directions).
#
#   blender -b -P bl_game.py -- <config.json>
#
# Unites : 1 unite Blender = 1 pixel du sprite d'origine (horizontalement) ; Z vers le haut ; le point d'ancrage
# du sprite (cx, cy) est l'origine au sol. Direction k : le modele tourne de -k*45 degres autour de Z, la camera
# reste fixe (elle regarde vers +Y, inclinee de 39 degres). Chaque image est rendue a la taille du cadre d'origine
# multipliee par k (cadre w x h, ancre cx, cy) : le resultat se superpose pixel pour pixel au sprite d'origine.
#
# config : {"model": chemin (.obj .glb .gltf .fbx .blend), "import": {...}, "engine": "WORKBENCH"|"CYCLES",
#           "samples": 32, "k": 4, "phi_deg": 39, "lights": {...}, "shadow": true,
#           "jobs": [{"d": 0, "w": 83, "h": 89, "cx": 31, "cy": 69, "frame": 1, "out": "x.png"}, ...]}
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
cfg = json.load(open(argv[0]))
PHI = math.radians(cfg.get('phi_deg', 39.0))
K = cfg.get('k', 4)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path, opts):
    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)
    if ext == '.obj':
        bpy.ops.wm.obj_import(filepath=path, forward_axis=opts.get('forward', 'Y'), up_axis=opts.get('up', 'Z'))
    elif ext in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True)
    elif ext == '.blend':
        with bpy.data.libraries.load(path) as (src, dst):
            dst.objects = src.objects
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
    else:
        raise ValueError(ext)
    new = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new('SC_root', None)
    bpy.context.scene.collection.objects.link(root)
    for o in new:
        if o.parent is None:
            o.parent = root
    # placement : rotation/echelle/translation du modele dans le repere du jeu
    m = opts.get('matrix')
    if m:
        root.matrix_world = Matrix(m)
    return root, new


def setup_camera(scene):
    cam_data = bpy.data.cameras.new('SC_cam')
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new('SC_cam', cam_data)
    scene.collection.objects.link(cam)
    cam.rotation_euler = (math.pi / 2 - PHI, 0.0, 0.0)
    scene.camera = cam
    cam_data.clip_start = 1.0
    cam_data.clip_end = 5000.0
    return cam


def frame_camera(scene, cam, w, h, cx, cy):
    """cadre w x h (pixels du sprite), ancre (cx, cy) : la camera voit exactement ce rectangle."""
    scene.render.resolution_x = int(w * K)
    scene.render.resolution_y = int(h * K)
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.0
    cam.data.ortho_scale = float(max(w, h))
    cam.data.sensor_fit = 'AUTO'
    sx_c = w / 2.0 - cx                     # centre du cadre, en coordonnees ecran (x a droite, y vers le haut)
    sy_c = cy - h / 2.0
    xa = Vector((1.0, 0.0, 0.0))
    ya = Vector((0.0, math.sin(PHI), math.cos(PHI)))       # haut de l'ecran
    v = Vector((0.0, math.cos(PHI), -math.sin(PHI)))       # direction de visee
    cam.location = xa * sx_c + ya * sy_c - v * 1500.0


def setup_lights(scene, lc):
    # lumiere fixe par rapport a la camera, comme dans les rendus d'origine (le modele tourne, pas la lumiere)
    for name, l in lc.items():
        ld = bpy.data.lights.new(name, l.get('type', 'SUN'))
        ld.energy = l.get('energy', 3.0)
        if hasattr(ld, 'angle'):
            ld.angle = math.radians(l.get('angle_deg', 2.0))
        ld.color = l.get('color', (1, 1, 1))
        if not l.get('shadow', True):                       # lumiere d'appoint sans ombre (visage sous la capuche)
            ld.use_shadow = False
            if hasattr(ld, 'cycles') and hasattr(ld.cycles, 'cast_shadow'):
                ld.cycles.cast_shadow = False
        lo = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(lo)
        az, el = math.radians(l.get('az_deg', 0)), math.radians(l.get('el_deg', 45))
        # direction d'ou vient la lumiere, dans le repere du monde
        dvec = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        lo.rotation_euler = (-dvec).to_track_quat('-Z', 'Y').to_euler()
    w = bpy.data.worlds.new('SC_world')
    scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get('Background')
    amb = cfg.get('ambient', 0.25)
    bg.inputs[0].default_value = (amb, amb, amb, 1.0)
    bg.inputs[1].default_value = 1.0


def setup_shadow_catcher(scene):
    bpy.ops.mesh.primitive_plane_add(size=600, location=(0, 0, 0))
    p = bpy.context.active_object
    p.name = 'SC_ground'
    p.is_shadow_catcher = True
    return p


def setup_render(scene):
    eng = cfg.get('engine', 'CYCLES')
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '16'
    scene.view_settings.view_transform = cfg.get('view_transform', 'Standard')
    if eng == 'WORKBENCH':
        scene.render.engine = 'BLENDER_WORKBENCH'
        scene.display.shading.light = 'FLAT'
        scene.display.shading.color_type = 'SINGLE'
        scene.display.render_aa = 'OFF'
    else:
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = cfg.get('samples', 32)
        scene.cycles.use_denoising = cfg.get('denoise', True)
        scene.cycles.max_bounces = cfg.get('bounces', 4)
        scene.render.filter_size = cfg.get('filter_px', 1.0)
        scene.render.threads_mode = 'AUTO'


def test_material(objs, rgb):
    mat = bpy.data.materials.new('SC_test')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*rgb, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.7
    for o in objs:
        if o.type == 'MESH':
            o.data.materials.clear()
            o.data.materials.append(mat)


def render_mask(scene, out):
    """silhouette de la creature seule (sans sol ni ombre), sans anticrenelage."""
    eng, ft = scene.render.engine, scene.render.film_transparent
    ground = bpy.data.objects.get('SC_ground')
    if ground:
        ground.hide_render = True
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'SINGLE'
    scene.display.render_aa = 'OFF'
    cd = scene.render.image_settings.color_depth
    scene.render.image_settings.color_depth = '8'
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    scene.render.image_settings.color_depth = cd
    scene.render.engine = eng
    scene.render.film_transparent = ft
    if ground:
        ground.hide_render = False


def main():
    reset()
    scene = bpy.context.scene
    root, objs = import_model(cfg['model'], cfg.get('import', {}))
    if cfg.get('test_color'):
        test_material(objs, cfg['test_color'])
    cam = setup_camera(scene)
    setup_render(scene)
    if cfg.get('engine', 'CYCLES') != 'WORKBENCH':
        setup_lights(scene, cfg.get('lights', {'key': {'az_deg': -40, 'el_deg': 50, 'energy': 4.0}}))
        if cfg.get('shadow', True):
            setup_shadow_catcher(scene)
    base = root.matrix_world.copy()
    for job in cfg['jobs']:
        if 'frame' in job:
            scene.frame_set(int(job['frame']))
        rot = Matrix.Rotation(-job['d'] * math.pi / 4.0, 4, 'Z')
        root.matrix_world = rot @ base
        frame_camera(scene, cam, job['w'], job['h'], job['cx'], job['cy'])
        scene.render.filepath = job['out']
        bpy.ops.render.render(write_still=True)
        if job.get('mask'):
            render_mask(scene, job['mask'])
        print('rendu', job['out'], flush=True)


main()
