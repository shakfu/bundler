from os.path import dirname
import sys


sys.path.insert(0, dirname(dirname(dirname(__file__))))

import bundler



#bundler.make_bundle("exe")
bundle = bundler.Bundle("demo")
bundle.create()