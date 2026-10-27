Coding instructions for all programming languages:

- Never use emojis anywhere unless explicitly requested.
- If no language is specified, assume the latest version of python.
- If tokens or other secrets are needed, pull them from an environment variable
- Prefer early returns over nested if statements.
- Prefer `continue` within a loop vs nested if statements.
- Prefer smaller functions over larger functions. Break up logic into smaller chunks with well-named functions.
- Use named constants for magic numbers, service urls, etc. Do not duplicate magic strings or numbers in code.
- Prefer constants with separators: `10_000` is preferred to `10000` (or `10_00` over `1000` in the case of a integer representing cents).
- Prefix feature-flag style constants with `{DISABLED,ENABLED}_`
- When I ask you to write code, prioritize simplicity and legibility over covering all edge cases, handling all errors, etc.
- When a particular need can be met with a mature, reasonably adopted and maintained package, I would prefer to use that package rather than engineering my own solution.
- Never add error handling to catch an error without being asked to do so. Fail hard and early with assertions and allow exceptions to propagate.
- When naming variables or functions, use names that describe the effect. For example, instead of `function handleClaimFreeTicket` (a function which opens a dialog box) use `function openClaimFreeTicketDialog`.
- Do not install missing system packages! Instead, ask me to install them for you.
- If terminal commands are failing because of missing variables or commands which are unrelated to your current task, stop your work and let me know.
- Don't worry about fixing lint errors or running lint scripts unless I specifically ask you to.
- When implementing workarounds for tooling limitations (like using `Any` for unresolvable types) or handling non-obvious edge cases, always add a brief inline comment explaining the technical reasoning.
- Reserve exact-width `#`-box section separators for long files requiring organization, though they should not be necessary in the large majority of cases (separate files is generally better).
- Complex functions, classes, etc (i.e. more than 10 lines or so) should have a concise docstr or comment describing their purpose.

Use line breaks to organize code into logical groups. Instead of:

```python
if not client_secret_id:
    raise ClientError("Invalid client secret")
session_id = client_secret_id.split("_secret")[0]
```

Prefer:

```python
if not client_secret_id:
    raise ClientError("Invalid client secret")

session_id = client_secret_id.split("_secret")[0]
```

**DO NOT FORGET**: keep your responses short, dense, and without fluff. I am a senior, well-educated software engineer, and hate long explanations.

### Code Comments

Default to no comment. Names, structure, and the command itself should explain what the code does.

The reader is a world-class engineer who may not know this domain or every third-party system. Add a concise one-line comment only when they would otherwise miss *why*:

- a business rule the code can't express
- non-obvious behavior or a gotcha in an external API, library, or tool
- a workaround for a tooling limitation (e.g. `Any` for an unresolvable type)
- a non-obvious edge case being handled

If the comment restates the next line, its names, or the command's flags, delete it.

Bad, restates the command:

```just
# install shared agent skills into the global skills dir
pnpx skills add https://github.com/iloveitaly/ai-skills -g --all
```

Good, explains a tool limitation the code can't show:

```just
# docker can't copy files out of an image, only a container, so create a throwaway one
docker create --name tmp-js-container {{JAVASCRIPT_IMAGE_TAG}}
docker cp tmp-js-container:/app/build/production/client public
```

- Describe behavior as it exists today—don't frame comments around version history or "old vs new."
- Do not remove existing comments.
- Do not capitalize or add periods at the end of single-line comments.

### Git Usage

- Do not automatically commit changes unless I explicitly ask you to.
- Never generate merge commits.

### Important Workflow Rules

Pay careful attention to these instructions when running tests, generating database migrations, or otherwise figuring out how to operate this project:

- Run `just` to understand the more important workflow commands.
  - Run `just --list` to see all available pre-written workflow development commands.
- **IMPORTANT:** Never manually set environment variables that are required. You can set optional variables for debugging, but any missing required environment variables is an error that should be reported and you should stop your work immediately.
- Do not worry about cleaning up the environment. This is done automatically.
- Run python code with `uv run python`
- Use `pytest` to run tests. If tests fail because of a configuration, environment, or system error: let me know and stop working.
  - Initially run `pytest --ignore=tests/integration` then only run `pytest tests/integration`
  - When debugging integration tests look at `$PLAYWRIGHT_RESULT_DIRECTORY`. There's a directory for each test failure. In that directory you fill find a `failure.html` containing the rendered DOM of the page on failure and a screenshot of the contents. Use these to debug why it failed.
- Do not attempt to create or run database migrations. Pause your work and let me know you need a migration run.
  - If you receive errors about missing migrations, missing tables, database connectivity, etc, stop your work and let me know.

## Mise

globs: mise*toml, .mise/tasks/**/*

- Docs: https://mise.jdx.dev/llms.txt
- When using mise tasks prefer `#MISE` comments over shell implementation of argument parsing, input validation, etc

## Shell Scripts

globs: **/*.sh

- Prefer zsh (assume latest version) over bash when you are certain it exists
- Prefer stricter error handling over silent failure.
- Hoist common environment variables to the top of the script.
- Add a `Description:` comment at the top of the script to describe what the script does. 1-4 lines max.
- Document conditional exits with a one-line explanation if it's not obvious.
- Add line breaks between logical groups of code.

## Justfiles

globs: just/*.just

- Docs: https://raw.githubusercontent.com/casey/just/master/README.md
- Never use `just_executable()` to reference the executable for `just`. If `just` DNE, then something is wrong adn you should stop your work and let me know.
- You should not have to mutate `$PATH`. If you cannot find an expected binary, stop your work and let me know.
- Do not create aliases unless explicitly asked
- Separate scripts larger than 5 lines with newlines and comments for non-obvious logic
- Do not use inline shebang unless it differs from the default
- Use `_` convention, not `[private]`
- Use uppercase for shell variable

Use the following script execution configuration:

```justfile
# zsh is the default shell under macos, let's mirror it everywhere
set shell := ["zsh", "-ceuB", "-o", "pipefail", "-o", "extended_glob"]

# determines what shell to use for [script]
set script-interpreter := ["zsh", "-euB", "-o", "pipefail", "-o", "extended_glob"]
```

## Pytest Tests

globs: tests/**/*.py

- Look first to `app.factories.*` instead of `app.models.*` to generate any required database state
  - For example, to create and persist a `Distribution` record `DistributionFactory.save()`
  - If a factory doesn't exist for the model you are working with, create one.
  - You can customize one or more params in a factory using `DistributionFactory.save(host="custom_host.com)`
- Use `faker` factory to generate emails, etc.
- Do not mock or patch unless I instruct you to. Test as much of the application stack as possible in each test.
- If you get lazy attribute errors, or need a database session to share across logic, use the `db_session` fixture to fix the issue.
  - Note that when writing route tests a `db_session` is not needed for the logic inside of the route.
- When testing Stripe, use the sandbox API. Never mock out Stripe interactions unless explicitly told to.
- Omit obvious docstrs and comments. Add comments for non-obvious but easy-to-miss lines that are key to what the test is checking.
- Do not add multiple tests for a one-line change.
- If test state setup requires more than three distinct factories, you should probably create a new factory to represent this particular state.
- Add pre-condition assertions when setup is load-bearing.
- If a `monkeypatch` is truly needed, a one-line comment on why. Prefer full-stack testing over mocking.

### Example Test

Below is an example test, you'll notice the following:

- Docstr is omitted since the purpose of the test is obvious
- Comment about the `county` is added since it's the main point of the test
- Newline between test setup, functionality under test, and assertions against result
- `api_app_url_path_for` helper is used instead of hardcoded routes

```python
from app.generated.fastapi_typed_routes import api_app_url_path_for
import json


def test_calculate_quote_unknown_county(client):
    payload = {
        "subscriber": {"age": 35, "gender": "M"},
        # fake county to ensure error is thrown
        "county": "NotACounty",
    }

    response = client.post(
        api_app_url_path_for("composite_quote"),
        json=payload,
    )

    assert_status(response, status.HTTP_422_UNPROCESSABLE_CONTENT)
```

### File Structure

* If there's more than a handful of tests in a folder, you should probably create subfolders.
* File name should be related to the file or primary class / functionality the test is covering. Do not add a component to the test name that exists in the test file path.
  * Example: `app/routes/unauthenticated/quote.py` should be `tests/routes/unauthenticated/quote_test.py`
* `tests/routes/{unauthenticated,authenticated}` and a handful of top-level test files for fastapi API route testing.
* `tests/integration/` for browser tests
* Reusable test helpers go in `tests/**/utils.py`.
* Duplicating assertion setup once or twice is fine; beyond that, put it in `tests/**/assertions.py`

## Python App

globs: **/*.py

Here's how the python application is organized:

- `app/lib/` is for code that is not specified to this application and with some effort could extracted into a external package.
- `app/helpers` is for larger reusable modules that if they weren't specific to this application, could be extracted into their own package.
- `app/utils` are small helper functions that are specific to a particular page or area of the application.
- `app/__init__.py` is the entrypoint for the application which is run when _anything_ is executed (fastapi, celery, etc).
  - It primarily runs `configure_*` commands for any `app.configuration.*` modules. These modules primary setup API clients, database connections, python language configuration, etc.
  - Also makes sure anything that mutates global state loads early.
- FastAPI server and routes are specified in `app/routes/`
- SQLModels are specified in `app/models/`
- Files within `app/commands/` should have:
  - Are not designed for CLI execution, but instead are interactor-style internal commands.
  - Should not be used on the queuing system
  - A `perform` function that is the main entry point for the command.
  - Look at existing commands for examples of how to structure the command.
  - Use `TypeID` for any parameters that are IDs of models.
- Files within `app/jobs/` should have:
  - Are designed for use on the queuing system.
  - A `perform` function that is the main entry point for the job.
  - Look at existing jobs for examples of how to structure the job.
  - Use `TypeID | str` for any parameters that are IDs of models.
- When referencing a command, use the full-qualified name, e.g. `app.commands.transcript_deletion.perform`.
- When queuing a job or `perform`ing it in a test, use the full-qualified name, e.g. `app.jobs.transcript_deletion.perform`.
- `app/cli/` is for scripts or CLI tools that are specific to the application.
- Webhooks should be fired in the model layer, not in a router or command.
- Lifecycle logic (status/state transitions, webhook enqueue, access grants) should live on the model. Commands, routes, etc should not re-implement `after_save`-style logic.
- Alias classes which are commonly used in the application. This makes it easier to grep for instances of that class without worrying about namespace clashes.
  - Example: `from botocore.exceptions import ClientError as BotoCoreClientError` instead of a plain `ClientError`.
  - `BaseModel` from `activemodel` is commonly used in `models/*.py`, so `pydantic`'s `BaseModel` should be aliased to `PydanticBaseModel`

### 3rd Party APIs

- Always use an official client library if it exists.
- Be thoughtful about metadata fields. Only put data there for (a) reporting or (b) a joining key a downstream consumer actually reads. Do not duplicate keys or data in metadata fields without a clear and documented purpose.
- Log unexpected API responses or shapes to Sentry.

### Python Test Code Organization

* `tests/**/utils.py` is for test-specific code that is not a fixture or a factory.
* `app/factories/` is the single source of truth for factories used by tests, local playground code, and dev seeding helpers.
  This is in the `app/` folder so that it can be used by seeding scripts.
* `tests/**/assertions.py` all custom `assert_*` functions should go here.
* `tests/**/conftest.py` is for test-specific fixtures. This is the only place you should put fixtures.
* `tests/{commands,routes,jobs,models}/` map to corresponding application categories under `app/`.
* `tests/integration/` is for browser tests.
  * Certain complex 3rd party dependencies (like Stripe, Clerk, etc) may require complex helpers. If they do, create a
    dedicated helper file in `tests/integration/**` (i.e. `stripe.py`, `clerk.py`, etc) to contain helper methods.

### Factories

globs: app/factories/**/.py

* Each model should get it's own file under `app/factories/model_name.py`
* `ActiveModelFactory` (which is a polyfactory subclass) should be used.
* Use `BaseFactory.__faker__` to generate more specific fake data for important fields (used in routes, etc)
* Prefer `slug = BaseFactory.__faker__.unique.slug` to `slug = Use(lambda: BaseFactory.__faker__.unique.slug())`
* Only override factory fields that differ from defaults.

#### Factory Example

```python
class ScreeningFactory(ActiveModelFactory[Screening]):
    funding_goal = lambda: BaseFactory.__faker__.random_int(min=0, max=2000_00)

    ticket_price = DEFAULT_TICKET_PRICE
    status = ScreeningStatus.active

    # always None
    funding_ending_at = None

    # pick entry from a fixed list
    zip_code = lambda: BaseFactory.__faker__.random_element(elements=REAL_ZIP_CODES)

    host_name = BaseFactory.__faker__.name
    host_description = lambda: BaseFactory.__faker__.paragraph(nb_sentences=2)

    # this method runs before the model is persisted to the database
    @classmethod
    def post_build(cls, model):
        # if the user does not pass in a important relationship during creation, you can generate a factory fallback
        if not model.distribution_id:
            model.distribution_id = DistributionFactory.save().id

        return model.save()

    # runs after the model is persisted to the database
    @classmethod
    def post_save(cls, model):
        return model.save()
```

### Database & ORM

When accessing database records:

* SQLModel (wrapping SQLAlchemy) is used
* `Model.one(primary_key)` or `Model.get(primary_key)` should be used to retrieve a single record
* Do not manage database sessions, these are managed by a custom tool
  * Use `TheModel(...).save()` to persist a record
  * Use `TheModel.where(...).order_by(...)` to query records. `.where()` returns a SQLAlchemy select object that you can further customize the query.
  * To iterate over the records, you'll need to end your query chain with `.all()` which returns an interator: `TheModel.where(...)...all()`
* Instead of repulling a record `order = HostScreeningOrder.one(order.id)` refresh it using `order.refresh()`

When writing database models:

* Don't use `Field(...)` unless required (i.e. when specifying a JSON type for a `dict` or pydantic model using `Field(sa_type=JSONB)`). For instance, use `= None` instead of `= Field(default=None)`.
* Add enum classes close to where they are used, unless they are used across multiple classes (then put them at the top of the file)
* Use `ModelName.foreign_key()` when generating a foreign key field
* Store currency as an integer, e.g. $1 = 100.
* `before_save`, `after_save(self):`, `after_updated(self):` are lifecycle methods (modelled after ActiveRecord) you can use.
* Prefer to add constraints to the model over the frontend.

Example:

```python
from pydantic import BaseModel as PydanticBaseModel
from activemodel import BaseModel
from typeid import TypeID
from activemodel.mixins import (
    PydanticJSONMixin,
    SoftDeletionMixin,
    TimestampsMixin,
    TypeIDPrimaryKey,
)


# pydantic models should be defined outside of the model class if they are used in other codes or models
class Video(PydanticBaseModel):
    title: str
    "name of the video"


class Distribution(BaseModel, TimestampsMixin, SoftDeletionMixin, table=True):
    """
    Triple-quoted strings for multi-line class docstring
    """

    # nest enum definition classes inside the model
    # use `DistributionState` instead of `State` to avoid postgres enum name conflicts
    class DistributionState(StrEnum):
        pending = "pending"
        active = "active"
        archived = "archived"

    id: TypeID[Literal["dst"]] = TypeIDPrimaryKey("dst")

    date_field_with_comment: datetime | None = None
    "use a string under the field to add a comment about the field"

    # no need to add a comment about an obvious field; no need for line breaks if there are no field-level docstrings
    title: str = Field(unique=True)
    state: DistributionState = DistributionState.pending

    optional_field: str | None = None

    videos: list[Video] = Field(
        sa_type=JSONB,
        nullable=False,
        default_factory=list,
        # ensures there is a empty list when the record is created
        sa_column_kwargs={"server_default": sa.text("'[]'")},
    )
    "videos available alongside the main film"

    # here's how relationships are constructed
    doctor_id: TypeID = Doctor.foreign_key()
    doctor: Doctor = Relationship()

    @computed_field
    @property
    def order_count(self) -> int:
        return self.where(Order.distribution_id == self.id).count()
```

## Python Route Tests

globs: tests/routes/**/*.py

- Polyfactory is the [factory](app/factories/) library in use. `ModelNameFactory.build()` is how you generate factories.
- Use `assert_status(response)` instead of `assert response.status_code == status.HTTP_200_OK`
- Do not reference routes by raw strings. Instead, use the typed route helpers defined in `app/generated/fastapi_typed_routes.py`.

## Python

globs: **/*.py

When writing Python:

* Assume the latest python, version 3.13.
* Prefer Pathlib methods (including read and write methods, like `read_text`) over `os.path`, `open`, `write`, etc.
* docstrs and comments:
  * If a docstring needs formatting, use markdown. Use Google Style.
  * Prefer docstr to multi-line comments at the top of a function or file.
  * If a docstr does not span multiple lines, do not use triple-quoted strings.
  * If a comment or docstr is a single line, do not end it in a period.
  * Add a newline after all docstrs.
* Do not create `__init__` files unless specifically instructed
* Use Pydantic models over dataclass or a typed dict.
* Use SQLAlchemy for generating any SQL queries.
* Use `click` for command line argument parsing.
* Use `log.info("the message", the_variable=the_variable)` instead of `log.info("The message: %s", the_variable)` or `print` for logging. This object can be found at `from app import log`.
  * Log messages should be lowercase with no leading or trailing whitespace.
  * No variable interpolation in log messages.
  * Do not coerce database IDs, dates, or Path objects to `str`
* Do not fix import ordering or other linting issues.
* Never edit or create any files in `migrations/versions/`
* Place all comments on dedicated lines immediately above the code statements they describe. Avoid inline comments appended to the end of code lines.
* Do not `try/catch` raw `Exceptions` unless explicitly told to. Prefer to let exceptions raise and cause an explicit error.
* Always make an explicit copy before mutating a dictionary that you did not create in the current narrow scope.
* Never use `from __future__`
* Always use `re.compile(pattern, re.VERBOSE)` and inline `#` comments to document the logic of each capture group or condition in any complex regular expression.
* **IMPORTANT** never edit app/generated/ files. These are autogenerated.

### Package Management

- Use `uv add` to add python packages. No need for `pip compile`, `pip install`, etc.

### Typing

* Assume the latest pyright version
* Prefer modern typing: `list[str]` over `List[str]`, `dict[str, int]` over `Dict[str, int]`, etc.
* Prefer to keep typing errors in place than eliminate type specificity:
  * Do not add ignore comments such as `# type: ignore`
  * Never add an `Any` type.
  * Do not `cast(object, ...)`

### Data Manipulation

* Prefer `funcy` utilities to complex list comprehensions or repetitive python statements.
* `import funcy as f` and `import funcy_pipe as fp`
* Some utilities to look at: `f.compact`

For example, instead of:

```python
params: dict[str, str] = {}
if city:
    params["city"] = city
if state_code:
    params["stateCode"] = state_code
```

Use:

```python
params = f.compact({"city": city, "stateCode": stateCode})
```

### Date & DateTime

* Use the `whenever` library for datetime + time instead of the stdlib date library. `Instant.now().format_iso()`
* DateTime mutation should explicitly opt in to a specific timezone `SystemDateTime.now().add(days=-7)`

## Shell

globs: **/*.sh

- Assume zsh for any shell scripts. The latest version of modern utilities like ripgrep (rg), fdfind (fd), bat, httpie (http), zq (zed), jq, procs, rsync are installed and you can request I install additional utilities.

## Terraform

globs: infra/**/*.tf

- All "bootstrap" secrets required to run the terraform code should be `export`ed in the Justfile. The Justfile is guarded so agents cannot run it, ensuring that required secrets are not available to agents ensures that terraform cannot be run by an agent.
- Don't add a `locals` for a variable only used a single time
- Don't add `output` resources unless specifically asked
- Use `~> 9.9.0` style provider version pinning
- Consult the terraform MCP when using an external module. Module surfaces change often.
- When creating a worker, always set the `compatibility_date` to the current date.
- Add `# sourced from ENV` for any `variable` sourced from the ENV.
- Uppercase all `TF_VAR_*`
- Put `locals` at the top of the file
- Reference Terraform-managed resources directly; add a data source only when a verified provider limitation requires it or the resource is managed elsewhere.

### File Structure

* `mise.toml` opentofu, environment variables, and other configuration required for terraform.
* `onepassword_secrets.tf` extracts secrets from 1Password that are required to run the terraform code. Secrets should be pulled from here, and not ENV.
* `providers.tf` defines the providers to use.
* `variables.tf` defines "global" variables, including those sourced from the ENV.
* `deployment_state.tf` stores the terraform state in a remote bucket.
* `Justfile` contains the commands to run the terraform code. Never run it directly.

<!-- END CLONED INSTRUCTIONS -->
