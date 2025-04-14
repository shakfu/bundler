.PHONY: all dylib clean test test_runtime demo

all: test


dylib:
	@echo "the install_name section here is key"
	@$(CC) -dynamiclib -std=gnu99 ratings.c \
		-current_version 1.0 \
		-compatibility_version 1.0 \
		-fvisibility=hidden \
		-install_name @rpath/libRatings.A.dylib \
		-o libRatings.A.dylib

dependent:
	@echo "location of dylib is specified as in the libs directory."
	@$(CC) dependent.c -L. -lRatings.A -Wl,-rpath,@executable_path/libs -o dependent

demo:
	@$(CC) -dynamiclib -std=gnu99 ratings.c \
		-current_version 1.0 \
		-compatibility_version 1.0 \
		-fvisibility=hidden \
		-o libRatings.A.dylib
	@$(CC) dependent.c -L. -lRatings.A -o demo
	@python3 test_app.py

runtime:
	@$(CC) -o runtime runtime.c


test: dylib dependent
	@mkdir libs && mv libRatings.A.dylib ./libs
	@./dependent


test_runtime: dylib runtime
	@echo "needs to be next to dylib because it hardcoded at the c level."
	@./runtime

clean:
	@rm -rf libs dependent runtime libRatings.A.dylib demo demo.app

