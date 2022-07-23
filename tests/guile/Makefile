NAME = guile-3.0
CFLAGS = $(shell pkg-config --cflags $(NAME))
LDFLAGS = $(shell pkg-config --libs $(NAME))

test_guile: clean
	@gcc $(CFLAGS) -o test_guile test_guile.c $(LDFLAGS)

test_guile.app: test_guile
	@python3 test_guile_app.py

test: test_guile.app

.PHONY: clean bundle

clean:
	@rm -rf test_guile.app
	@rm -f test_guile

