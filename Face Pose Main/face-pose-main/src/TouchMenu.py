import cv2
import numpy as np
import TouchKeyboard
import time
import Settings
import FaceRecognizer

class Button:

    id = 0
    text = ""
    yTop = 0
    yBottom = 0
    colorR = (0, 0, 0)
    colorT = (0, 0, 0)
    textOffset = 0
    textOrg = 0
    onClickEvent = None

    def __init__(self, id, text, yTop, yBottom, colorR=(60, 60, 60), colorT=(255, 255, 255), onClick=None):
        self.id = id
        self.text = text
        self.yTop = yTop
        self.yBottom = yBottom
        self.colorR = colorR
        self.colorT = colorT
        self.onClickEvent = onClick
        self.textOffset = 6 if self.id == 0 else 10
        self.textOrg = self.yTop + \
            (self.yBottom - self.yTop) // 2 + self.textOffset

    def draw(self, img, xMax):
        cv2.rectangle(img, (0, self.yTop), (xMax, self.yBottom),
                      self.colorR, cv2.FILLED)
        textOrg = self.yTop + (self.yBottom - self.yTop) // 2 + self.textOffset
        cv2.putText(img, self.text, ((xMax // 2) - 64, textOrg),
                    cv2.FONT_HERSHEY_PLAIN, fontScale=1.75, color=self.colorT, thickness=2)
        return img


class TouchMenu(object):

    size = (150, 450)
    imageSize = (650, 450)
    buttonHeight = 100
    menuImg = cv2.resize(cv2.imread("resources/black_bg.jpg"), size)
    buttonCount = 0
    buttons = []

    # Add User Window
    touchKeyboard = None
    showAddUserWindow = False
    cancelButtonSize = 80
    addUserWindowTitle = "Add new user"
    addUserState = "name"  # "name", "password", "done", or "error"
    newUserName = ""

    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = super(TouchMenu, cls).__new__(cls)
        return cls.instance

    def __init__(self):
        self.touchKeyboard = TouchKeyboard.TouchKeyboard()
        self.touchKeyboard.touchOffsets = (0, 130)

        cancelButtonImg = cv2.circle(
            np.zeros((130, 130, 3)), (65, 65), self.cancelButtonSize // 2, (0, 0, 255), cv2.FILLED)
        cancelButtonImg = cv2.polylines(cancelButtonImg, [np.array(
            [[40, 40], [90, 90]]).astype(int)], True, (255, 255, 255), 8)
        cancelButtonImg = cv2.polylines(cancelButtonImg, [np.array(
            [[90, 40], [40, 90]]).astype(int)], True, (255, 255, 255), 8)
        self.textBoxImg = np.hstack((np.zeros((130, 670, 3)), cancelButtonImg))

    def addButton(self, text, colorR=(60, 60, 60), colorT=(255, 255, 255), onClick=None):
        yTop = self.buttonCount * self.buttonHeight
        self.buttonCount += 1
        yBottom = self.buttonCount * self.buttonHeight
        self.buttons.append(Button(self.buttonCount, text,
                            yTop, yBottom, colorR, colorT, onClick))

    def start(self):
        for button in self.buttons:
            self.menuImg = button.draw(self.menuImg, self.size[0])

    def getMenuImg(self):
        return self.menuImg

    def clickEvent(self, event, x, y, flags, param):
        if (x > self.imageSize[0] and x < self.imageSize[0] + self.size[0]):
            if (event) == cv2.EVENT_LBUTTONDOWN:
                for button in self.buttons:
                    if (y > button.yTop and y < button.yBottom):
                        if button.onClickEvent is not None:
                            button.onClickEvent()

    def calibrate(self):
        print("Calibrate")

    def settings(self):
        print("Settings")

    def addUserTouchEvent(self, event, x, y, flags, param):
        if x > (800 - 130) and x < 800 and y > 0 and y < 130:  # Cancel Button
            if event == cv2.EVENT_LBUTTONDOWN:
                print("Cancel")
                cv2.destroyWindow(self.addUserWindowTitle)
                self.showAddUserWindow = False

        elif x > (800 - 160) and x < 800 and y > (450 - 65) and y < 480:  # Enter Button
            if event == cv2.EVENT_LBUTTONDOWN:
                if self.addUserState == "name":
                    if len(self.touchKeyboard.typedText) > 0:
                        self.newUserName = self.touchKeyboard.typedText
                        self.touchKeyboard.typedText = ""
                        self.addUserState = "password"
                elif self.addUserState == "password":
                    if len(self.touchKeyboard.typedText) > 0:
                        if (self.touchKeyboard.typedText == Settings.password or self.touchKeyboard.typedText == Settings.masterPassword):
                            self.touchKeyboard.typedText = ""
                            self.addUserState = "done"
                        else:
                            self.touchKeyboard.typedText= ""
                            self.addUserState = "error"

        else:
            self.touchKeyboard.clickEvent(event, x, y, flags, param)

    def addUser(self, user_image):
        cv2.namedWindow(self.addUserWindowTitle)
        cv2.moveWindow(self.addUserWindowTitle, -2, 0)
        cv2.setMouseCallback(self.addUserWindowTitle, self.addUserTouchEvent)
        self.showAddUserWindow = True
        self.addUserState = "name"

        while self.showAddUserWindow:
            if self.addUserState == "name":
                img = self.getInputWindowImage(
                    "Enter name for new user", (135, 0, 0), self.touchKeyboard.typedText)
            elif self.addUserState == "password":
                passwordField = "*" * len(self.touchKeyboard.typedText)
                img = self.getInputWindowImage("Enter password", (135, 0, 0), passwordField)
            elif self.addUserState == "done":
                fr = FaceRecognizer.FaceRecognizer()
                fr.newUser(self.newUserName, user_image)
                img = self.getInputWindowImage("User added successfully", (0, 175, 0), "")
                cv2.imshow(self.addUserWindowTitle, img)
                cv2.waitKey(1)
                time.sleep(1.5)
                cv2.destroyWindow(self.addUserWindowTitle)
                break
            elif self.addUserState == "error":
                img = self.getInputWindowImage("Incorrect password", (0, 0, 175), "")
                cv2.imshow(self.addUserWindowTitle, img)
                cv2.waitKey(1)
                time.sleep(1.5)
                self.touchKeyboard.typedText = ""
                self.addUserState = "password"

            cv2.imshow(self.addUserWindowTitle, img)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                cv2.destroyWindow(self.addUserWindowTitle)
                break
            
    def getInputWindowImage(self, line1, line1Color, line2):
            img = np.vstack(
                (self.textBoxImg, self.touchKeyboard.getKeyboardImage()))
            cv2.putText(img, line1, (10, 50),
                        cv2.FONT_HERSHEY_COMPLEX_SMALL, 2, line1Color, 2)
            cv2.putText(img, line2, (420, 110),
                        cv2.FONT_HERSHEY_PLAIN, 3.2, (255, 255, 255), 2)
            return img


if __name__ == "__main__":

    run = True

    def stop():
        global run
        run = False
        cv2.destroyAllWindows()

    tm = TouchMenu()
    tm.buttonHeight = 100
    tm.imageSize = (0, 0)
    tm.addButton("Add User", colorR=(0, 155, 0), onClick=tm.addUser)
    tm.addButton("Calibrate", onClick=tm.calibrate)
    tm.addButton("Settings", colorR=(255, 140, 0), onClick=tm.settings)
    tm.addButton("  Exit", colorR=(0, 0, 255), onClick=stop)
    tm.start()

    cv2.namedWindow("Touch Menu")
    cv2.setMouseCallback("Touch Menu", tm.clickEvent)

    while run:
        cv2.imshow("Touch Menu", tm.getMenuImg())
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
