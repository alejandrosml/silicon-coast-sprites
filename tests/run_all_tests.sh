#!/bin/bash
# lance toutes les suites hors ligne a la suite ; un journal par suite dans ../all/tests/
cd "$(dirname "$0")"
mkdir -p ../all/tests
for t in "test_allscene.py ../all/scene_hd" "test_layoutF.py" "test_subshade.py" "test_clearwalls.py" "test_suite.py" "test_cases2.py" "test_equip.py" "test_equip2.py" "test_realwalls.py" "test_regress.py"; do
  name=$(echo $t | cut -d' ' -f1 | sed 's/.py//')
  start=$(date +%s)
  timeout 5400 python3 $t > ../all/tests/$name.log 2>&1
  code=$?
  end=$(date +%s)
  pass=$(grep -c "^PASS" ../all/tests/$name.log)
  fail=$(grep -c "^FAIL" ../all/tests/$name.log)
  echo "$name exit=$code PASS=$pass FAIL=$fail $((end-start))s" >> ../all/tests/summary.txt
done
echo DONE >> ../all/tests/summary.txt
