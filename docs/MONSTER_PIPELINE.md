# Monster pipeline: from a BG2:EE sprite to an HD 3D re-render, with no manual step

This document describes the automatic chain used to remake the creatures of Baldur's Gate II: Enhanced Edition in
3D and render them back as SC-HD sprites (×4, see [FORMAT.md](../FORMAT.md)). It covers the creatures that use
animation type 7000 ("monster", one BAM file per sequence). The chain was written after the first manual test (the
ogre, October 2026) and the lessons learnt from it; its aim is that nothing has to be fixed by hand.

The scripts are in [`pipeline3d/`](../pipeline3d) (comments in French). They read the game's own files, which
are not in this repository; `pipeline3d/session_cloud.sh` runs one creature in a cloud session, in slices of a few
minutes, with its data taken from a private dataset. The SC-HD conversion of new art (stage 10) uses options of
`sc_convert.py` and `sc_verify.py` that are not published yet, so that stage runs in the main session for now.

## Principle

The original game decides. Silhouette, proportions, posture, outfit, held objects and colours come from the original
sprite; the 3D version adds detail (materials, relief, light, smoother motion), never a different creature. Every
decision the chain takes is measured against the original sprite, and every result is checked by numbers before it
is kept.

The rules behind those checks:

| Rule | Check |
|---|---|
| Same size | height of the first idle frame, front view, within ±3 % |
| Same posture | head position relative to the hips, side view, within 2 sprite pixels |
| Same brightness | mean luminance of the creature (shadow excluded), first idle frame, front view |
| Same colours | median colour of head, torso and legs (Lab distance) |
| Held objects | made separately, held at the original grip point, they fall to the ground at death |
| Smoother motion | idle 32 frames, attacks 24, conjure/cast 24, hit 16, death 24 (game plays creatures at 15 fps) |
| Walk | keeps the original frame count (otherwise the feet slide), one full gait cycle, stride matched to the original foot speed |
| Rhythm | sequences whose frame table repeats a pattern (casting loops, twitching on the ground) keep the original table |
| Shadow | ground shadow shaped like the original one (palette index 1) |
| Engine | every frame checked by `sc_verify.py` (markers, geometry, anchor, probe, palette) |

## Stages

`chaine.py <RESREF>` runs the stages below in order. Each stage writes its results in the creature's work folder
and is skipped when they already exist, so an interrupted run resumes where it stopped.

1. **origine** (`prepare.py`): reads the 13 BAM files of the creature (`G1`, `G11`–`G15`, `G2`, `G21`–`G26`), the
   frame tables of the 13 sequences in the 9 recorded directions, the creature masks, the enlarged views (front,
   side, back) and the measurements (height, luminance, colour bands, foot speed in the walk). Sequences that are
   pixel-identical copies of another one (for example `A4 = A1`) are detected and rendered only once.
2. **dessin** (`reference.py dessin`, GPU): an image-edit model (Qwen-Image-Edit-2511) turns the enlarged views and
   a written description of the creature into a realistic reference drawing, full body, A-pose, empty hands. Several
   seeds are drawn and scored against the sprite (colour bands, overall likeness, body proportions with the drawing
   brought to the sprite's height, framing, single piece); the best one is kept.
3. **modele** (`reference.py modele`, GPU): TRELLIS.2 turns the drawing into a textured mesh (300,000 faces, 2048
   texture). A malformed result is retried with another seed.
4. **rig** (`auto_rig.py`): a skeleton with Mixamo bone names and no fingers is placed from front and side
   silhouettes of the mesh (crotch, armpits, elbows, wrists, knees, ankles, neck, head), then skinned by heat
   diffusion on a watertight remesh (largest piece only) and transferred to the real mesh. A test pose measures
   stretched edges and unweighted vertices; a doubtful result is redone with a finer remesh.
5. **arme** (`arme.py`): when the original holds an object (for example the githyanki's long sword), it is modelled
   separately (blade with a central ridge, guard, grip, pommel, at the original length and colour) and attached to
   the hand bone. The roll of the grip around the hand axis is fitted later on the original silhouettes.
6. **mouvements** (`mouvements.py`): for each sequence, about 30 motion-capture candidates (a converted Mixamo
   library, filtered by keywords and by the creature's archetype: claws, fists, caster, sword) are retargeted onto
   the skeleton, rendered as silhouettes with the game camera at the sprite's scale (front and side, held object
   included) and compared with the original frames (1 − IoU). A coarse pass searches the whole capture with a time
   window of bounded speed (0.7 to 1.4 times the target duration); a fine pass aligns each original frame inside a
   band around the linear alignment. The best capture and passage are kept; attacks stay different from each
   other. Then:
   - posture: upper back and neck are tilted until the head sits where the original's head sits, side view
     (median of the top of the silhouette against the upper legs, so that a held weapon does not pull the
     measure); idle first, then guard and walk within 10° of it;
   - size: the scale is set so that the first idle frame has the original height;
   - walk: one full gait cycle of the capture (two steps, found as the deepest true dip of the leg-pose
     self-similarity between 0.55 and 2.5 s), played in the original number of frames (game walks are often
     faster than captures: up to 2.3 times), stride scaled (0.6 to 1.4) to the original foot speed;
   - loops (idle, guard, walk) are closed exactly (the residual between the last and first pose is spread over the
     cycle); idle motion is damped to the original's amplitude;
   - sequences with a repeating table get one new frame per unique original frame, and each replayed segment is
     closed the same way;
   - single-frame sequences and the "on the ground" sequence reuse the pose of the most similar original frame of
     another sequence (death for the ground pose).
7. **lumiere** (`lumiere.py`): key light −108°/60°, fill light from the camera without shadow, ambient; energies are
   adjusted until the first idle frame has the original mean luminance. The ground shadow is computed without
   rendering (mesh points projected along the sun onto the ground, then closed: a solid, hard-edged shadow like the
   game's); 144 sun directions are tried at once, and the one whose visible shadow covers the original shadow
   (palette index 1) best is kept.
8. **rendu**, **ombre** (`jobs7000.py`, `bl_anim.py`): every frame of every sequence in the 9 directions, Cycles,
   ×4, one Blender process per sequence; then the shadow pass (a few seconds for all frames).
9. **bams** (`bams7000.py`): renders to BAM, with the 88–255 palette rebuilt for the new colours, ordered dithering,
   a per-channel colour gain that brings the median colour back to the original without changing its luminance,
   the original frame tables where they are kept, shadow pixels to index 1.
10. **schd** (`sc_convert.py`, then `sc_verify.py`): SC-HD files built from the new HD frames (their own palette,
    their own frame counts and extents), verified frame by frame.
11. **controle** (`controle.py`): report (size, luminance, colours, posture, shadow, verification, chosen motions
    and their scores), silhouette sheet (original | 3D for every sequence) and animated previews (original ×4 |
    new HD, four directions, game rhythm).

## Running it

Each creature is independent, so the creatures run in parallel cloud sessions: the GPU stages (2 and 3) run first in
one session, which watches a 24-hour GPU budget so that the included ZeroGPU quota is never exceeded; then one
session per creature runs `amorce.sh <RESREF>`, which fetches the tools and data, installs Blender 5.2.3, runs the
chain from stage 4 and uploads the results. A creature takes about 5 minutes of motion matching and two to three
hours of rendering on two CPU cores.

Environment variables: `SC_SRC` (original BAM files), `SC_BLENDER`, `SC_MOCAP` (motion library), `SC_SPRITES`
(this repository, for `tools/` and `tables/`), `SC_MONSTRES` (work folders).

## Results of a run

Per creature: `hd/*.BAM` (HD BAM files), `schd/*.BAM` (SC-HD files to put in `override`), `verif.json`,
`controle/rapport.md`, `controle/planche_mouvements.png`, `controle/<RESREF>_<SEQ>.gif`, and every intermediate file
(reference drawing, mesh, rig, chosen motions, light), so that a later change of rule only reruns the stages after
it.

## Known limits

- The chain needs a full-body reference drawing; creatures far from a humanoid shape (no legs, many limbs) need a
  different skeleton and are not handled yet.
- Motion is limited to the motion library (about 400 captures); the scores in the report show how close each chosen
  motion is to the original.
- Held objects are modelled for swords so far.
