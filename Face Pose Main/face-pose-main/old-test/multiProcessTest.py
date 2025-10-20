import queue
import cv2
import FaceRecognizer
import multiprocessing

fr = FaceRecognizer.FaceRecognizer()
fr.low_res = True

fr.addUser("Yigit", "train_img/yigit.jpg")
fr.addUser("Yigit", "train_img/yigit-gozluklu.jpg")


def face_recognition_worker(image_queue, result_queue, stop_event):
    while not stop_event.is_set():
        try:
            image = image_queue.get(timeout=1)
        except Exception:
            continue

        fr.process(image)

        if fr.getUser() is not None:
            result = fr.getUser().name
        else:
            result = None
        try:    
            result_queue.put(result)
        except BrokenPipeError or EOFError:
            continue


if __name__ == "__main__":
    max_queue_size = 10

    manager = multiprocessing.Manager()
    image_queue = manager.Queue(maxsize=max_queue_size)
    result_queue = manager.Queue()
    stop_event = multiprocessing.Event()

    recognition_process = multiprocessing.Process(target=face_recognition_worker,
                                                  args=(image_queue, result_queue, stop_event))
    recognition_process.start()

    cap = cv2.VideoCapture(0)

    while not stop_event.is_set():
        ret, frame = cap.read()

        if image_queue.full():
            image_queue.get()
        image_queue.put(frame)

        if not result_queue.empty():
            result = result_queue.get()
            if result is not None:
                print(result)

        cv2.imshow("Image", frame)
        try:
            if cv2.waitKey(1) == ord('q') or not cv2.getWindowProperty("Image", cv2.WND_PROP_VISIBLE):
                stop_event.set()
                face_recognition_worker.join()
        except Exception:
            continue

    cap.release()
    cv2.destroyAllWindows()