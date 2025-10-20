import cv2
import time
import numpy as np


class Button():
    def __init__(self, pos, text, size=[65, 65], textColor=(255, 255, 255)):
        self.pos = pos
        self.size = size
        self.text = text
        self.textColor = textColor
        self.highlighted = False
        self.lastClickTime = 0


class TouchKeyboard:

    __buttons = []
    __keyboardImage = None

    typedText = ""
    maxTextLength = 7
    hOffset = 5
    vOffset = 5
    touchOffsets = [0, 0]  # x, y

    keys = [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
        ["A", "S", "D", "F", "G", "H", "J", "K", "L", "<-"],
        ["Z", "X", "C", "V", "B", "N", "M", ".", "Enter"]
    ]

    def __init__(self):
        for i in range(len(self.keys)):
            for j, key in enumerate(self.keys[i]):
                if i == 3 and j == 8:  # Enter Key
                    self.__buttons.append(
                        Button([80 * j + self.hOffset, 80 * i + self.vOffset], key, [160, 65]))

                elif i == 2 and j == 9:  # Backspace Key
                    self.__buttons.append(
                        Button([80 * j + self.hOffset, 80 * i + self.vOffset], key, [85, 65]))

                else:
                    self.__buttons.append(
                        Button([80 * j + self.hOffset, 80 * i + self.vOffset], key))

    def getKeyboardImage(self, backgroundImage=None):

        if backgroundImage is None:
            self.__keyboardImage = np.zeros((320, 800, 3))

        else:
            self.__keyboardImage = cv2.resize(backgroundImage, (800, 320))

        for button in self.__buttons:
            x, y = button.pos
            textColor = button.textColor

            if button.highlighted:
                textColor = (0, 225, 0)
                if (button.text != "<-" or button.text != "Enter") and (len(self.typedText) >= self.maxTextLength):
                    textColor = (0, 0, 215)
                if time.time() - button.lastClickTime > 0.05:
                    button.highlighted = False

            cv2.putText(self.__keyboardImage, button.text, (x + 20, y + 45),
                        cv2.FONT_HERSHEY_PLAIN, 2, textColor, 3)

        return self.__keyboardImage

    def clickEvent(self, event, x, y, flags, param):
        correctedX = x - self.touchOffsets[0]
        correctedY = y - self.touchOffsets[1]

        for button in self.__buttons:
            if (correctedX < button.pos[0] + button.size[0] and correctedX > button.pos[0] and
                    correctedY < button.pos[1] + button.size[1] and correctedY > button.pos[1]):

                if event == cv2.EVENT_LBUTTONDOWN:
                    button.lastClickTime = time.time()
                    button.highlighted = True

                    if button.text == "<-":
                        self.typedText = self.typedText[:-1]
                    elif button.text == "Enter":
                        continue
                    else:
                        if len(self.typedText) < self.maxTextLength:
                            if len(self.typedText) == 0:
                                self.typedText = button.text
                            else:
                                self.typedText += button.text.lower()


if __name__ == "__main__":
    import numpy as np
    tk = TouchKeyboard()
    cv2.namedWindow("Touch Keyboard")
    cv2.setMouseCallback("Touch Keyboard", tk.clickEvent)

    while True:
        img = tk.getKeyboardImage()
        cv2.imshow("Touch Keyboard", img)
        if cv2.waitKey(1) & 0xFF == ord('q') or cv2.waitKey(1) & 0xFF == ord('Q') or cv2.waitKey(1) & 0xFF == 27 or cv2.getWindowProperty("Touch Keyboard", cv2.WND_PROP_VISIBLE) == False:
            break
