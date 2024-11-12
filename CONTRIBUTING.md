# Python code style

## Black

We use [Black](https://github.com/psf/black) to format our code:

```
black <Python files>
```

## isort

We use [isort](https://pycqa.github.io/isort/) to format import blocks:

```
isort --profile black <Python files>
```

## Before committing

Make sure your code is formatted using the above tools.
For example, you can install a pre-commit hook.
