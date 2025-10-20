import cv2
import cvzone
from cvzone.FaceMeshModule import FaceMeshDetector
import time

detector = FaceMeshDetector(maxFaces=1)
cap = cv2.VideoCapture(0)

ratioList = []
raiseCounter = 0
counter = 0
color = (255, 0, 255)
eyesClosed = False

while True:
    img = cv2.flip(cap.read()[1], 1)
    faces = detector.findFaceMesh(img, draw=False)[1]
    
    if faces:
        face = faces[0]
 
        leftBrowUp = face[105]
        leftFaceUp = face[67]
        midFaceUp = face[10]
        midFaceDown = face[152]
        d1 = detector.findDistance(leftBrowUp, leftFaceUp)[0]
        d2 = detector.findDistance(midFaceDown, midFaceUp)[0]
        browRatio = d1 / d2 * 100
        ratioList.append(browRatio)
        if len(ratioList) > 5:
            ratioList.pop(0)
        ratioAvg = sum(ratioList) / len(ratioList)
        print(ratioAvg)
 
        cv2.line(img, leftBrowUp, leftFaceUp, (0, 200, 0), 2)
        cv2.line(img, midFaceUp, midFaceDown, (0, 200, 0), 2)
 
        if ratioAvg < 14.5 and counter == 0:
            raiseCounter += 1
            color = (0,200,0)
            counter = 1
        if counter != 0:
            counter += 1
            if counter > 10:
                counter = 0
                color = (255,0, 255)
 
        cvzone.putTextRect(img, f'Raise Count: {raiseCounter}', (50, 100), colorR=color)
        
    cv2.imshow("Image", img)
    if(cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty("Image", cv2.WND_PROP_VISIBLE) < 1):
        break