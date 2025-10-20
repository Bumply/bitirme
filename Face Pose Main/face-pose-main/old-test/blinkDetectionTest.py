import cv2
import cvzone
from cvzone.FaceMeshModule import FaceMeshDetector

detector = FaceMeshDetector(maxFaces=1)
cap = cv2.VideoCapture(0)

idList = [22, 23, 24, 26, 110, 157, 158, 159, 160, 161, 130, 243]
ratioList = []
blinkCounter = 0
counter = 0
color = (255, 0, 255)
eyesClosed = False

while True:
    img = cv2.flip(cap.read()[1], 1)
    faces = detector.findFaceMesh(img, draw=False)[1]
    
    if faces:
        face = faces[0]
        for id in idList:
            cv2.circle(img, face[id], 2, color, cv2.FILLED)
 
        leftUp = face[159]
        leftDown = face[23]
        leftLeft = face[130]
        leftRight = face[243]
        lenghtVer, _ = detector.findDistance(leftUp, leftDown)
        lenghtHor, _ = detector.findDistance(leftLeft, leftRight)

 
        cv2.line(img, leftUp, leftDown, (0, 200, 0), 2)
        cv2.line(img, leftLeft, leftRight, (0, 200, 0), 2)
 
        ratio = int((lenghtVer / lenghtHor) * 100)
        ratioList.append(ratio)
        if len(ratioList) > 5:
            ratioList.pop(0)
        ratioAvg = sum(ratioList) / len(ratioList)
        #print(ratioAvg)
 
        if ratioAvg < 35 and counter == 0:
            blinkCounter += 1
            color = (0,200,0)
            counter = 1
        if counter != 0:
            counter += 1
            if counter > 10:
                counter = 0
                color = (255,0, 255)
 
        cvzone.putTextRect(img, f'Blink Count: {blinkCounter}', (50, 100), colorR=color)
        
    cv2.imshow("Image", img)
    if(cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty("Image", cv2.WND_PROP_VISIBLE) < 1):
        break