import cv2
from imutils.video import VideoStream
from enum import Enum

class CaptureSource(Enum):
    CV2 = 1
    IMUTILS = 2

class Capture:
    __cap__ = None
    __source__ = None

    def __init__(self, source, camera=0):
        self.__source__ = source

        if self.__source__ == CaptureSource.CV2:
            self.__cap__ = cv2.VideoCapture(camera)
        elif self.__source__ == CaptureSource.IMUTILS:
            self.__cap__ = VideoStream(src=camera).start()
        else:
            print("Invalid capture source")
            raise ValueError("Invalid capture source")

    def getFrame(self):
        
        if (self.__source__ == CaptureSource.CV2):
            frame = self.__cap__.read()[1]
        
        elif(self.__source__ == CaptureSource.IMUTILS):
            frame = self.__cap__.read()

        elif(self.__source__ == CaptureSource.PICAMERA):
            frame = self.__cap__.capture_array()

        if (frame is None):
            print("No Frame")
        else:
            return cv2.flip(frame, flipCode=1)
