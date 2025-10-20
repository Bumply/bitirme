import cv2
from imutils.video import VideoStream

cap = cv2.VideoCapture(0)
while True:
    success, frame = cap.read()
    cv2.imshow("Frame", frame)
    if cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty("Frame", cv2.WND_PROP_VISIBLE) < 1:
        break
cap.release()
