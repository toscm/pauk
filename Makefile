PHP        ?= $(HOME)/.local/bin/php
COMPOSER   ?= $(HOME)/.local/bin/composer
MARIADB    ?= $(HOME)/.local/mariadb-11.8
PY         ?= python3
VENV        = cli/.venv
ROOT       := $(CURDIR)

DEV_PORT    = 33061
DEV_DATADIR = $(ROOT)/api/var/devdb
DEV_ENV     = PAUK_DB_HOST=127.0.0.1 PAUK_DB_PORT=$(DEV_PORT) \
              PAUK_DB_USER=root PAUK_DB_PASS= PAUK_DB_NAME=pauk_dev

.PHONY: setup serve test test-php test-cli db-start db-stop db-migrate \
        tunnel deploy rollback backup-fetch

setup:
	cd api && $(COMPOSER) install --no-interaction
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet -e './cli[dev]'
	@echo "setup complete"

db-start:
	@test -d $(DEV_DATADIR) || $(MARIADB)/scripts/mariadb-install-db \
	    --no-defaults --basedir=$(MARIADB) --datadir=$(DEV_DATADIR) \
	    --auth-root-authentication-method=normal --skip-test-db >/dev/null
	@if ! $(MARIADB)/bin/mariadb --no-defaults -h 127.0.0.1 -P $(DEV_PORT) \
	    -u root -e 'SELECT 1' >/dev/null 2>&1; then \
	    $(MARIADB)/bin/mariadbd --no-defaults --basedir=$(MARIADB) \
	        --datadir=$(DEV_DATADIR) --port=$(DEV_PORT) \
	        --bind-address=127.0.0.1 --socket=$(DEV_DATADIR).sock \
	        --skip-name-resolve --pid-file=$(DEV_DATADIR).pid \
	        2>$(DEV_DATADIR).log & \
	    sleep 2; \
	fi
	@$(MARIADB)/bin/mariadb --no-defaults -h 127.0.0.1 -P $(DEV_PORT) -u root \
	    -e 'CREATE DATABASE IF NOT EXISTS pauk_dev'
	@echo "dev db running on 127.0.0.1:$(DEV_PORT)"

db-stop:
	@test -f $(DEV_DATADIR).pid && kill "$$(cat $(DEV_DATADIR).pid)" || true

db-migrate: db-start
	cd api && $(DEV_ENV) $(PHP) bin/migrate.php

serve: db-migrate
	cd api && $(DEV_ENV) $(PHP) -S 127.0.0.1:8080 public/index.php

test: test-php test-cli

test-php:
	scripts/with-testdb.sh sh -c 'cd api && $(PHP) vendor/bin/phpunit'

test-cli:
	scripts/with-testdb.sh $(VENV)/bin/pytest cli/tests -q

tunnel:
	ssh -N -L 33306:db5021384667.hosting-data.io:3306 ionos

deploy:
	scripts/deploy.sh

rollback:
	scripts/rollback.sh

backup-fetch:
	scripts/backup-fetch.sh
