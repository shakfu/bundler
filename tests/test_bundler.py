from os.path import dirname, commonpath
import sys
import subprocess

sys.path.insert(0, dirname(dirname(dirname(__file__))))

import bundler

load_paths_scm = subprocess.check_output(
    ["guile", "-c", "(display %load-path)"], encoding="utf-8"
)
load_paths = load_paths_scm[1:-1].split()
guile_path = commonpath(load_paths)

#bundler.make_bundle("test_guile", add_to_resources=[guile_path])
bundle = bundler.Bundle("test_guile", add_to_resources=[guile_path])
bundle.create()

