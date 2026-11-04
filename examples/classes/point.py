"""A record-and-method interpretation of point.lp, with integer coordinates."""


class Point:
    def __init__(self, x_value, y_value):
        self.x_value = x_value
        self.y_value = y_value

    def shifted_x(self, delta_value):
        return self.x_value + delta_value


if __name__ == "__main__":
    print(Point(3, 4).shifted_x(2))
