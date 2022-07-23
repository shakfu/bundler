# Tell Guile where to find specific guile modules GUILE_LIBS
# can be used to override the path to Guile's own modules; likewise,
# GUILE_COMPILED_LIBS overrides the path to Guile's precompiled
# modules.
# GUILE_LIBS=
# GUILE_COMPILED_LIBS=
GHOME="${PWD}/test_guile.app/Contents/Resources/guile"
GUILE_LOAD_PATH="${GHOME}/3.0;${GHOME}/site/3.0;${GHOME}/site"

#GUILE_LOAD_COMPILED_PATH={GHOME}/lib/guile/3.0/ccache;{GHOME}/lib/guile/2.2/ccache/gnucash/deprecated;{GNC_HOME}/lib/guile/2.2/site-ccache;{GUILE_COMPILED_LIBS};{GUILE_LOAD_COMPILED_PATH}

# Tell Guile where to find GnuCash specific shared libraries
#LTDL_LIBRARY_PATH={SYS_LIB};{GNC_LIB}
