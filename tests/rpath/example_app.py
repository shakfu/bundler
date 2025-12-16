import sys
from os.path import dirname

sys.path.insert(0, dirname(dirname(dirname(__file__))))

import bundler

#bundler.make_bundle("exe")
bundle = bundler.Bundle("demo")
bundle.create()
