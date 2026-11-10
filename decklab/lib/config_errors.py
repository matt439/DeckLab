"""Configuration errors that can be shown without quoting private file contents."""


class InvalidConfig(ValueError):
    """A local configuration problem with a safe, actionable message."""


class ConfigSyntaxError(InvalidConfig):
    """A JSON syntax location, with no source text or parser message retained."""

    def __init__(self, line, column):
        if not valid_location(line, column):
            raise ValueError("Invalid configuration error location")
        self.line, self.column = line, column
        super().__init__(syntax_message(line, column))


def valid_location(line, column):
    return type(line) is int and type(column) is int and 0 < line <= 2 ** 31 - 1 and 0 < column <= 2 ** 31 - 1


def syntax_message(line, column):
    return f"decklab/config.json isn't valid JSON: line {line}, column {column}"
