import cv2
import cvzone
import numpy as np

cap = cv2.VideoCapture(0)
bg = cv2.imread("resources/black_bg.jpg")
bg = cv2.resize(bg, (150, 400))
cvzone.putTextRect(bg, "Calibrate", pos=(0, 50), scale=2, thickness=2, colorR=(60,60,60), offset=30)

while True:
    camImg = cap.read()[1]
    camImg = cv2.resize(camImg, (600, 400))

    img = np.hstack((camImg, bg))

    cv2.imshow("Image", img)
    cv2.resizeWindow("Image", 750, 400)

    if cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty("Image", cv2.WND_PROP_VISIBLE) < 1:
        break
