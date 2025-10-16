# encoding: utf-8
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

# Authentication for user filing issue (must have read/write access to repository to add issue to)
USERNAME = 'LIAOGuangmao'

# The repository to add this issue to
REPO_OWNER = 'LIAOGuangmao'
REPO_NAME = 'ArXivDaily_StarFormation'

# Set new submission url of subject
NEW_SUB_URL = 'https://arxiv.org/list/astro-ph/new'

# Keywords to search
KEYWORD_LIST = ["star formation", "star-forming", "molecular cloud", "interstellar medium", "cloud", "clump", "core", "filament", "atomic gas", "N-PDF", "initial conditions", "IRDC", "deuterium", "prestellar", "starless", "turbulence", "magnetic", "virial"]
# Keywords to exclude
KEYWORD_EX_LIST = ["galaxies", "galaxy cluster", " AGN ", "standard candle", "X-ray binar", "solar corona"]
# Note that the 'Keywords' above are actually searched in the abstract instead of the real keyword section. 
