import face_recognition

class User:
    
    name = ""
    image_path = ""
    face_encoding = None
    
    def __init__(self, name, image_path):
        self.name = name
        self.image_path = image_path
        self.face_encoding = self.__encode_face()
    
    def __encode_face(self):
        user_image = face_recognition.load_image_file(self.image_path)
        return face_recognition.face_encodings(face_image=user_image, model="small")[0]