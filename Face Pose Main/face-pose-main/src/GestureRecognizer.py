import numpy as np
import landmark_indexes
import time
import cv2
from enum import Enum


class Gesture(Enum):
    NONE = 0
    BROW_RAISE = 1
    BLINK = 2


class GestureRecognizer(object):

    __brow_raise_threshold__ = 10000
    __normalized_ratio__ = 0
    __ratioList__ = []
    __weightList__ = []
    __avgRatio__ = 0

    __truePitch__ = 0
    __trueYaw__ = 0
    
    brow_raised = False
    browThresholdCalibrated = False
    browCalibrationEntryTime = -1
    calibrationInstruction = "    Raise your eyebrows"
    eyebrowRaisedRatio = 0
    eyebrowLoweredRatio = 0
    print = False
    
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = super(GestureRecognizer, cls).__new__(cls)
        return cls.instance
        
    def calibrate (self):
        newThreshold = 0
        
        if self.browCalibrationEntryTime == -1:
            self.browCalibrationEntryTime = time.time()
            self.eyebrowRaisedRatio = 0
            self.eyebrowLoweredRatio = 0
            self.calibrationInstruction = "    Raise your eyebrows"
        
        elapsedTime = time.time() - self.browCalibrationEntryTime
        
        if (elapsedTime >= 3 and elapsedTime < 6):
            if self.eyebrowRaisedRatio == 0:
                self.eyebrowRaisedRatio = self.__normalized_ratio__
            self.calibrationInstruction = "    Lower your eyebrows"

        if (elapsedTime >= 6 and elapsedTime < 7):
            if (not self.browThresholdCalibrated):
                if self.eyebrowLoweredRatio == 0:
                    self.eyebrowLoweredRatio = self.__normalized_ratio__

                # Check if calibrated properly
                if (self.eyebrowLoweredRatio > self.eyebrowRaisedRatio):
                    self.eyebrowRaisedRatio = 0
                    self.eyebrowLoweredRatio = 0
                    self.calibrationInstruction = "    Raise your eyebrows"
                    self.browCalibrationEntryTime = time.time()
                    return self.calibrationInstruction, newThreshold
                
                elif (self.eyebrowLoweredRatio < self.eyebrowRaisedRatio + 20 and self.eyebrowLoweredRatio > self.eyebrowRaisedRatio - 20):
                    self.eyebrowRaisedRatio = 0
                    self.eyebrowLoweredRatio = 0
                    self.calibrationInstruction = "    Raise your eyebrows"
                    self.browCalibrationEntryTime = time.time()
                    return self.calibrationInstruction, newThreshold

                print("Raised ratio: " + str(self.eyebrowRaisedRatio))
                print("Lowered ratio: " + str(self.eyebrowLoweredRatio))
                newThreshold = self.eyebrowLoweredRatio + ((self.eyebrowRaisedRatio - self.eyebrowLoweredRatio) * 70.0 / 100.0)
                print("New threshold: " + str(newThreshold))
                self.browThresholdCalibrated = True
                self.browCalibrationEntryTime = -1
                
        return self.calibrationInstruction, newThreshold


    def setBrowRaiseThreshold(self, threshold):
        self.__brow_raise_threshold__ = threshold

    def process(self, face, pitch, yaw, pitchOffset, yawOffset):
        self.__truePitch__ = pitch - pitchOffset
        self.__trueYaw__ = yaw - yawOffset
        self.__checkBlink(face)
        self.__checkEyebrowRaise(face)

    def __checkBlink(self, face):
        return

    def __checkEyebrowRaise(self, face):

        if face == []:
            return

        head_height = self.__findDistance(
            face[landmark_indexes.MOUTH_UPPER], face[landmark_indexes.MID_FACE_UP])

        if self.__trueYaw__ < 0:
            brow_to_head_distance = self.__findDistance(
                face[landmark_indexes.LEFT_BROW_UP], face[landmark_indexes.LEFT_FACE_UP])

        else:
            brow_to_head_distance = self.__findDistance(
                face[landmark_indexes.RIGHT_BROW_UP], face[landmark_indexes.RIGHT_FACE_UP])

        distRatio = head_height / brow_to_head_distance * 100

        if self.__truePitch__ > 0:
            correctedRatio = distRatio - (self.__truePitch__ * 1.8)
        else:
            correctedRatio = distRatio - (self.__truePitch__ * 1.2)

        if np.abs(self.__trueYaw__) > 18:
            correctedRatio = correctedRatio - np.abs(self.__trueYaw__ * 2.6)

        self.__ratioList__.append(correctedRatio)

        if len(self.__ratioList__) >= 10:
            self.avgRatio = np.average(
                self.__ratioList__)

            weight = 1 / (1 - (abs(self.avgRatio -
                                   correctedRatio) / self.avgRatio))

            self.__weightList__.append(weight)

            if len(self.__weightList__) >= 10:
                self.__normalized_ratio__ = np.average(
                    self.__ratioList__, weights=self.__weightList__)
                self.__weightList__.pop(0)

            else:
                self.__normalized_ratio__ = np.average(
                    self.__ratioList__)

            self.__ratioList__.pop(0)

        else:
            self.__normalized_ratio__ = correctedRatio

        if (self.__normalized_ratio__ > self.__brow_raise_threshold__):
            self.brow_raised = True
        else:
            self.brow_raised = False

        if self.print:
            print(f"Ratio: {int(distRatio)} | Corrected: {int(correctedRatio)} | Normalized: {int(self.__normalized_ratio__)} | Threshold: {self.__brow_raise_threshold__} | Raised: {self.brow_raised}")

    def __findDistance(self, p1, p2):
        x_distance = p2[0] - p1[0]
        y_distance = p2[1] - p1[1]
        return np.sqrt(x_distance**2 + y_distance**2)

    def getGesture(self):
        if self.brow_raised:
            return Gesture.BROW_RAISE
        else:
            return None
