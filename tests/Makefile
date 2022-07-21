CFLAGS = \
	-D_THREAD_SAFE \
	-I/usr/local/Cellar/guile/3.0.8/include/guile/3.0 \

LDFLAGS = -lpthread -lguile-3.0.1

bundle: test_guile
	@python3 ../bundler.py

test_guile: clean
	@gcc $(CFLAGS) -o test_guile test_guile.c $(LDFLAGS)

.PHONY: clean bundle

clean:
	@rm -rf test_guile.app
	@rm -f test_guile

