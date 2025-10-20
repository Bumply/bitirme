import cv2
import mediapipe as mp
import numpy as np
import time


class FaceMesh(object):

    detect_confidence = 0.7
    track_confidence = 0.8
    pitch = 0
    yaw = 0
    pitchOffset = 0
    yawOffset = 0
    face = []

    calibrated = False
    calibrationEntryTime = -1
    calibrationInstruction = "Position your head neutrally"

    angle_coefficient = 1.0

    __FACE_OUTLINE_INDEXES__ = [33, 263, 1, 61, 291, 199]
    __FACE_MESH__ = mp.solutions.face_mesh.FaceMesh(min_detection_confidence=detect_confidence,
                                                    min_tracking_confidence=track_confidence)
    __DRAWING_SPEC__ = mp.solutions.drawing_utils.DrawingSpec(
        thickness=1, circle_radius=1)
    
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = super(FaceMesh, cls).__new__(cls)
        return cls.instance

    def calibrate(self):
        
        pitchOffset = 0
        yawOffset = 0
        
        if self.calibrationEntryTime == -1:
            self.calibrationEntryTime = time.time()
            self.yawOffset = 0
            self.pitchOffset = 0
            self.calibrationInstruction = "Position your head neutrally"
        
        elapsedTime = time.time() - self.calibrationEntryTime
        
        # Calibrate Pitch and Yaw Offsets
        if (elapsedTime >= 5 and elapsedTime < 8):
            self.calibrationInstruction = "           Stay still"

        if (elapsedTime >= 8 and elapsedTime < 13):
            pitchOffset = self.pitch * -1.0
            yawOffset = self.yaw * -1.0
            self.calibrationEntryTime = -1
            self.calibrated = True
            
        return self.calibrationInstruction, pitchOffset, yawOffset

    def process(self, image):

        image = cv2.resize(image, (683, 360))
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False  # To pass by reference
        results = self.__FACE_MESH__.process(image)

        img_h = image.shape[0]
        img_w = image.shape[1]
        
        del image

        face_3d = []
        face_2d = []
        self.face = []

        if results.multi_face_landmarks:

            for face_landmarks in results.multi_face_landmarks:

                # Get the indexes of each facial landmark
                for idx, lm in enumerate(face_landmarks.landmark):

                    x = int(lm.x * img_w)
                    y = int(lm.y * img_h)

                    self.face.append([x, y])

                    # Face outline coordinates
                    if idx in self.__FACE_OUTLINE_INDEXES__:
                        face_2d.append([x, y])
                        face_3d.append([x, y, (lm.z)])

                # Convert it to NumPy array
                face_2d = np.array(face_2d, dtype=np.float64)

                # Convert it to NumPy array
                face_3d = np.array(face_3d, dtype=np.float64)

                cam_matrix = np.array([[img_w, 0, img_h / 2],
                                       [0, img_w, img_w / 2],
                                       [0, 0, 1]])

                # Solve PnP
                rot_vec = cv2.solvePnP(
                    face_3d, face_2d, cam_matrix, 0)[1]

                # Get rotational matrix
                rotation_matrix = cv2.Rodrigues(rot_vec)[0]

                # TODO: experiment with rotation matrices
                rot_ratios = cv2.RQDecomp3x3(rotation_matrix)[0]

                # Calculate the head rotation in degrees
                self.__calculateHeadRotation(rot_ratios)

    def __calculateHeadRotation(self, ratios):
        self.pitch = np.round(
            ratios[0] * 180 * np.pi * self.angle_coefficient) + self.pitchOffset
        self.yaw = np.round(
            ratios[1] * 180 * np.pi * self.angle_coefficient) + self.yawOffset

    def getYawPitch(self):
        return self.yaw, self.pitch


if __name__ == "__main__":  # For testing purposes

    cap = cv2.VideoCapture(0)
    fm = FaceMesh()

    while True:
        image = cv2.flip(cap.read()[1], 1)  # Flip the image horizontally
        angle_coefficient = 1.0
        fm.process(image)
        # Add the text on the image
        cv2.putText(image, "Pitch: " + str(int(fm.pitch)), (450, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        cv2.putText(image, "Yaw: " + str(int(fm.yaw)), (450, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        cv2.imshow("Face Mesh", image)

        pressedKey = cv2.waitKey(1) & 0xFF

        if pressedKey == ord('q') or pressedKey == 27 or cv2.getWindowProperty("Face Mesh", cv2.WND_PROP_VISIBLE) < 1:
            break
