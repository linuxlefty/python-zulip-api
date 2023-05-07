class _Logger:
    def __init__(self, name: str):
        self.name = name
        self.logs: list[str] = list()

    def log(self, message: str):
        line = f"LOG:{self.name}:{message}"
        self.logs.append(line)
        print(line)
