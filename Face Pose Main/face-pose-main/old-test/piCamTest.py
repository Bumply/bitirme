import cv2
import os
import time
from picamera2 import Picamera2


picam2 = Picamera2()
picam2.start()

while True:
    image = picam2.capture_array()

    image = cv2.resize(image, (320, 240))
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    image = cv2.rotate(image, rotateCode=cv2.ROTATE_180)
    cv2.imshow('test', image)

    if cv2.waitKey(5) & 0xFF == ord('q') or cv2.getWindowProperty('test', cv2.WND_PROP_VISIBLE) < 1:
        break