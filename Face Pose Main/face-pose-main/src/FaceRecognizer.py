import cv2
import face_recognition
import User
import os

class FaceRecognizer(object):

    low_res = False
    recognize_confidence = 0.5

    __user_images_path = os.getcwd() + os.sep + "user_images"
    __image_face_locations = []
    __unknown_face_locations = []
    __image_face_encodings = []
    __known_face_encodings = []
    __users = []
    __matches = []
    __activeUserIndex = -1

    __activeUser = None
    
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = super(FaceRecognizer, cls).__new__(cls)
        return cls.instance
    
    def __getUserDirectories(self, path):
        subdir_list = []
        
        scan_result = os.scandir(path)
        for res in scan_result:
            if res.is_dir():
                subdir_list.append(res)
                
        return subdir_list
    
    def train(self):
        for user_dir in self.__getUserDirectories(self.__user_images_path):
            image_path = self.__user_images_path + os.sep + user_dir.name
            
            for user_img in os.scandir(user_dir):
                self.encodeUser(user_dir.name, image_path + os.sep + user_img.name)
                
    def newUser(self, name: str, image):
        for dir in self.__getUserDirectories(self.__user_images_path):
            if dir.name == name: # User directory already exists
                image_count = os.listdir(dir).__len__()
                os.chdir(self.__user_images_path + os.sep + name)
                cv2.imwrite(filename=str(image_count + 1) + ".jpg", img=image)
                return
        newDirPath = self.__user_images_path + os.sep + name
        os.mkdir(newDirPath)
        os.chdir(newDirPath)
        cv2.imwrite(filename="1.jpg", img=image)

    def encodeUser(self, name, image_path):
        user = User.User(name, image_path)
        self.__users.append(user)
        self.__known_face_encodings.append(user.face_encoding)

    def process(self, image):
        
        self.__reset_vars()
                        
        if self.low_res:
            image = cv2.resize(image, (0, 0), fx=0.25, fy=0.25)

        # Convert the image from BGR color (which OpenCV uses) to RGB color (which face_recognition uses)
        image = cv2.cvtColor(src=image, code=cv2.COLOR_BGR2RGB)

        # Find all the faces and face encodings in the current image of video
        self.__image_face_locations = face_recognition.face_locations(
            image, model="hog")
        self.__image_face_encodings = face_recognition.face_encodings(
            image, known_face_locations=self.__image_face_locations, model="small")


        for i, encoding in enumerate(self.__image_face_encodings):
            self.__matches += face_recognition.compare_faces(
                self.__known_face_encodings, encoding, self.recognize_confidence)

        for i, match in enumerate(self.__matches):
            if match:
                try:
                    self.__activeUser = self.__users[i % self.__users.__len__()]
                    self.__activeUserIndex = i % self.__users.__len__()
                except Exception as e:
                    print(e) 
                    self.__activeUser = None
                    self.__activeUserIndex = -1
                break
            else:
                self.__activeUser = None

        if self.__activeUser is None:
            return

        if self.__image_face_locations.__len__() > 1:
            for i, location in enumerate(self.__image_face_locations):
                if i == self.__activeUserIndex:
                    continue
                self.__unknown_face_locations.append(location)

            for unknown in self.__unknown_face_locations:
                if self.low_res:
                    cv2.rectangle(image, (unknown[3] * 4, unknown[0] * 4),
                                  (unknown[1] * 4, unknown[2] * 4), (0, 0, 0), -1)
                else:
                    cv2.rectangle(
                        image, (unknown[3], unknown[0]), (unknown[1], unknown[2]), (0, 0, 0), -1)
        
        return image
                    

    def __reset_vars(self):
        self.__image_face_locations = []
        self.__image_face_encodings = []
        self.__matches = []
        self.__activeUser = None
        self.__activeUserIndex = -1
        
    def getUser(self):
        return self.__activeUser
        
if __name__ == "__main__":
    fr = FaceRecognizer()
    fr.train()
    pass

    '''
    cap = cv2.VideoCapture(0)

    while True:
        image = cap.read()[1]
        image = fr.eventLoop(image)
        cv2.imshow("Test", image)
        
        if fr.__activeUser != None:
            print(fr.__activeUser.name)
        
        if cv2.waitKey(1) & 0xFF == ord('q') or cv2.getWindowProperty("Test", cv2.WND_PROP_VISIBLE) == False:
            cap.release()
            break
    '''