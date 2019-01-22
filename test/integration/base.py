import unittest
from dbt.adapters.factory import get_adapter
from dbt.config import RuntimeConfig
from dbt.main import handle_and_check
import dbt.main as dbt
import psycopg2
import sys
import os
import yaml

DBT_CONFIG_DIR = os.path.abspath(
    os.path.expanduser(os.environ.get("DBT_CONFIG_DIR", "/home/dbt_test_user/.dbt"))
)

DBT_PROFILES = os.path.join(DBT_CONFIG_DIR, "profiles.yml")


class TestArgs(object):
    def __init__(self, kwargs):
        self.which = "run"
        self.single_threaded = False
        self.profiles_dir = DBT_CONFIG_DIR
        self.__dict__.update(kwargs)


class DBTIntegrationTest(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super(DBTIntegrationTest, self).__init__(*args, **kwargs)

        self.test_schema_name = '"$my_test_schema"'

    def setUp(self):
        self.use_profile()
        self.use_default_project()
        self.load_config()

    def tearDown(self):
        if os.path.exists("dbt_project.yml"):
            os.remove("dbt_project.yml")
        if os.path.exists("packages.yml"):
            os.remove("packages.yml")
        self.run_sql("DROP SCHEMA IF EXISTS {} CASCADE" % self.test_schema_name)

    @property
    def project_config(self):
        return {}

    @property
    def test_path(self):
        path = sys.modules[self.__module__].__file__
        path = os.path.split(path)[0]
        return path

    @property
    def models_path(self, dirname="models"):
        return os.path.join(self.test_path, dirname)

    def postgres_profile(self):
        return {
            "config": {"send_anonymous_usage_stats": False},
            "test": {
                "outputs": {
                    "default2": {
                        "type": "postgres",
                        "threads": 4,
                        "host": "database",
                        "port": 5432,
                        "user": "root",
                        "pass": "password",
                        "dbname": "dbt",
                        "schema": "$test",
                    },
                    "noaccess": {
                        "type": "postgres",
                        "threads": 4,
                        "host": "database",
                        "port": 5432,
                        "user": "noaccess",
                        "pass": "password",
                        "dbname": "dbt",
                        "schema": "$test",
                    },
                },
                "target": "default2",
            },
        }

    def use_profile(self):
        if not os.path.exists(DBT_CONFIG_DIR):
            os.makedirs(DBT_CONFIG_DIR)

        profile_config = {}
        default_profile_config = self.postgres_profile()

        profile_config.update(default_profile_config)

        with open(DBT_PROFILES, "w") as f:
            yaml.safe_dump(profile_config, f, default_flow_style=True)

        self._profile_config = profile_config

    def load_config(self):
        # we've written our profile and project. Now we want to instantiate a
        # fresh adapter for the tests.
        # it's important to use a different connection handle here so
        # we don't look into an incomplete transaction
        kwargs = {"profile": None, "profile_dir": DBT_CONFIG_DIR, "target": None}

        config = RuntimeConfig.from_args(TestArgs(kwargs))

        adapter = get_adapter(config)

        adapter.cleanup_connections()
        connection = adapter.acquire_connection("__test")
        self.adapter_type = connection.type
        self.adapter = adapter
        self.config = config

    def run_sql(self, sql, fetch="None"):

        if sql.strip() == "":
            return

        conn = self.conn
        with conn.cursor() as cursor:
            try:
                cursor.execute(sql)
                conn.commit()
                if fetch == "one":
                    return cursor.fetchone()
                elif fetch == "all":
                    return cursor.fetchall()
                else:
                    return
            except BaseException as e:
                conn.rollback()
                print(sql)
                print(e)
                raise e

    def use_default_project(self, overrides=None):
        # create a dbt_project.yml
        base_project_config = {
            "name": "test",
            "version": "1.0",
            "test-paths": [],
            "source-paths": [self.models_path],
            "profile": "test",
        }

        project_config = {}
        project_config.update(base_project_config)
        project_config.update(self.project_config)
        project_config.update(overrides or {})

        with open("dbt_project.yml", "w") as f:
            yaml.safe_dump(project_config, f, default_flow_style=True)

    def run_dbt(self, args):

        if args is None:
            args = ["run"]

        res, success = handle_and_check(args)