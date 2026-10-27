#!/bin/bash
# valide les shaders comme GLSL 1.10 de bureau, avec le prefixe exact du moteur (DrawCreateProgram_GL)
D=$(dirname "$0")
PRE='#if !defined(GL_ES)
#define highp
#define mediump
#define lowp
#else
precision highp float;
#endif
'
rc=0
for f in "$@"; do
  b=$(basename "$f" .GLSL)
  case "$b" in VP*) ext=vert;; *) ext=frag;; esac
  out="$D/glslv/$b.$ext"
  { echo "#version 110"; echo "$PRE"; echo "// $b.glsl"; cat "$f"; } > "$out"
  if glslangValidator "$out" > "$D/glslv/$b.log" 2>&1; then echo "OK   $b"; else echo "FAIL $b"; cat "$D/glslv/$b.log"; rc=1; fi
done
exit $rc
