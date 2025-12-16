import sys
from os.path import dirname

sys.path.insert(0, dirname(dirname(dirname(__file__))))

import macbundler

# macbundler.make_bundle("exe")
bundle = macbundler.Bundle("demo")
bundle.create()
