''' Module imports '''
import Capture
from Capture import CaptureSource
import cv2
from GestureRecognizer import Gesture
import TouchMenu
import numpy as np
import time
import multiprocessing

''' Face Recognition Process Worker '''
def fr_worker(image_to_process, active_user, authenticated_event, new_user_added_event, fr_ready_event):
    import FaceRecognizer
    fr = FaceRecognizer.FaceRecognizer()
    fr.low_res = True
    fr.train()
    fr_ready_event.set()
    while True:
        if new_user_added_event.is_set():
            fr_ready_event.clear()
            fr.train()
            new_user_added_event.clear()
            fr_ready_event.set()
        
        if not authenticated_event.is_set():
            try:
                image = image_to_process.get()
                if image is None:
                    continue
                image = fr.process(image)
                image_to_process.set(None)

                if fr.getUser() is not None:
                    print(f"User Recognized: {fr.getUser().name}")
                    image_to_process.set(image) # send single user image to fm worker
                    active_user.set(fr.getUser().name)
                    authenticated_event.set()

            except Exception as e:
                print("fr worker exception: ", e)
                continue
        else:
            time.sleep(0.1)

''' Face Mesh Process Worker '''
def fm_worker(image_to_process, authenticated_event, pitch_yaw, control_wheelchair_event, calibrating_event, calibration_instruction, active_user, last_active_user):
    import FaceMesh
    import GestureRecognizer
    fm = FaceMesh.FaceMesh()
    gr = GestureRecognizer.GestureRecognizer()
    gr.print = False
    brow_raise_time = None
    pitchOffset = 0
    yawOffset = 0
    newBrowRaiseThreshold = 0
    while True:
        if authenticated_event.is_set():
            try:
                image = image_to_process.get()
                if image is None:
                    continue
                image_to_process.set(None)

                try:
                    if calibrating_event.is_set():
                        control_wheelchair_event.clear()
                        fm.calibrated = False
                        gr.browThresholdCalibrated = False
                        fm.calibrationEntryTime = -1
                        gr.browCalibrationEntryTime = -1
                        
                        while calibrating_event.is_set():
                            image = image_to_process.get()
                            if image is None:
                                continue
                            image_to_process.set(None)
                            fm.process(image)
                            
                            if fm.face == []:
                                authenticated_event.clear()
                                calibrating_event.clear()
                                active_user.set("")
                                control_wheelchair_event.clear()
                                fm.calibrated = False
                                gr.browThresholdCalibrated = False
                                fm.calibrationEntryTime = -1
                                gr.browCalibrationEntryTime = -1
                                continue
                            
                            if not fm.calibrated:
                                instruction, pitchOffset, yawOffset = fm.calibrate()
                                calibration_instruction.set(instruction)

                            elif not gr.browThresholdCalibrated:
                                gr.process(fm.face, fm.pitch, fm.yaw, fm.pitchOffset, fm.yawOffset)
                                instruction, newBrowRaiseThreshold = gr.calibrate()
                                calibration_instruction.set(instruction)

                            else:
                                calibration_instruction.set("   Calibration Complete")
                                
                                if last_active_user.get() != active_user.get():
                                    last_active_user.set(active_user.get())
                                    
                                fm.pitchOffset = pitchOffset
                                fm.yawOffset = yawOffset
                                gr.setBrowRaiseThreshold(newBrowRaiseThreshold)
                                    
                                time.sleep(1)
                                calibration_instruction.set("")                        
                                calibrating_event.clear() 
                                                
                    else:                        
                        fm.process(image)

                        if fm.face == []:
                            authenticated_event.clear()
                            calibrating_event.clear()
                            active_user.set("")
                            control_wheelchair_event.clear()
                            continue

                        pitch_yaw.set((fm.pitch, fm.yaw))

                        gr.process(fm.face, fm.pitch, fm.yaw,
                                fm.pitchOffset, fm.yawOffset)
                        
                        if gr.getGesture() == Gesture.BROW_RAISE:
                            if brow_raise_time is None:
                                brow_raise_time = time.time()
                                
                            if time.time() - brow_raise_time > 2:  
                                
                                if not control_wheelchair_event.is_set():
                                    control_wheelchair_event.set()
                                else:
                                    control_wheelchair_event.clear()

                                brow_raise_time = None
                                
                except Exception as e:
                    print("fm calibration exception: ", e)
                    

            except Exception as e:
                print("fm worker exception: ", e)
                continue
        else:
            time.sleep(0.1)


''' Communication Manager Process Worker '''
def cm_worker(pitch_yaw, obstacle_detected_event, control_wheelchair_event, home_steering_event):
    import CommManager
    cm = CommManager.CommManager()
    cm.log_to_console = False
    homed = False
    cm.start()
    
    stopMessageSent = False
    while True:        
        if home_steering_event.is_set():
            try:
                cm.home()
                home_steering_event.clear()
            except Exception as e:
                print("cm worker homing exception: ", e)
        
        if control_wheelchair_event.is_set():
            try:
                if stopMessageSent:
                    stopMessageSent = False
                    
                if not homed: 
                    cm.home()
                    time.sleep(1.2)
                    homed = True
                
                fPitch, fYaw = pitch_yaw.get()
                pitch = int(fPitch)
                yaw = int(fYaw)
                cm.eventLoop(pitch, yaw)
                if cm.obstacleDetected and not obstacle_detected_event.is_set():
                    obstacle_detected_event.set()
                elif not cm.obstacleDetected and obstacle_detected_event.is_set():
                    obstacle_detected_event.clear()
            except Exception as e:
                if Exception is PermissionError:
                    print("Permission Error: COM Port is disconnected or in use")
                else:
                    print("cm worker exception: ", e)
                continue
        else:
            if not stopMessageSent:
                stopMessageSent = True
                for _ in range(3):
                    cm.eventLoop(0, 0)
                homed = False
            time.sleep(0.1)


''' Main Process '''
if __name__ == "__main__":
    manager = multiprocessing.Manager()

    ''' Module instances '''
    cap = Capture.Capture(CaptureSource.CV2)
    tm = TouchMenu.TouchMenu()

    ''' Display Window Creation '''
    cv2.namedWindow("Wheelchair")
    cv2.resizeWindow("Wheelchair", 800, 450)
    cv2.moveWindow("Wheelchair", -2, 0)

    ''' Global variables '''
    run = True
    image = None
    addNewUser = False
    homeSteering = False

    ''' Shared Variables - Events '''
    image_to_process = manager.Value(np.ndarray, None)
    pitch_yaw = manager.Value(tuple, (0, 0))
    active_user = manager.Value(str, "")
    last_active_user = manager.Value(str, None)
    calibration_instruction = manager.Value(str, "")
    
    authenticated_event = manager.Event()
    calibrating_event = manager.Event()
    control_wheelchair_event = manager.Event()
    fr_ready_event = manager.Event()
    new_user_added_event = manager.Event()
    home_steering_event = manager.Event()
    obstacle_detected_event = manager.Event()

    '''' Subprocesses '''
    fr_process = multiprocessing.Process(
        target=fr_worker, name="fr_process", args=(image_to_process, active_user, authenticated_event, new_user_added_event, fr_ready_event))

    fm_process = multiprocessing.Process(
        target=fm_worker, name="fm_process", args=(image_to_process, authenticated_event, pitch_yaw, control_wheelchair_event, calibrating_event, calibration_instruction, active_user, last_active_user))

    cm_process = multiprocessing.Process(
        target=cm_worker, name="cm_process", args=(pitch_yaw, obstacle_detected_event, control_wheelchair_event, home_steering_event))

    ''' Function definitions '''
    def stop():
        global run
        run = False
        fr_process.terminate()
        cm_process.terminate()
        fm_process.terminate()
        print("Exit")

    def toggleCalibrate():
        global authenticated_event, calibrating_event

        if calibrating_event.is_set():
            calibrating_event.clear()

        elif authenticated_event.is_set():
            calibrating_event.set()
        
    def addNewUserCb():
        global addNewUser
        addNewUser = True
    
    def homeSteeringCb():
        global homeSteering
        homeSteering = True

    ''' Module configurations & initializations '''
    cv2.setMouseCallback("Wheelchair", tm.clickEvent)

    loading_screen_img = cv2.resize(cv2.imread("resources/atilim_logo_bg.jpg"), (800, 450))

    tm.buttonHeight = 112
    tm.imageSize = (650, 450)
    tm.addButton("Add User", colorR=(0, 155, 0), onClick=addNewUserCb)
    tm.addButton("Calibrate", onClick=toggleCalibrate)
    tm.addButton("  Home", colorR=(0, 0, 255), onClick=homeSteeringCb)
    tm.addButton("  Exit", colorR=(255, 0, 0), onClick=stop)
    tm.start()

    fr_process.start()
    cm_process.start()
    fm_process.start()

    ''' Main Loop '''
    while run:        
        image = cap.getFrame()
        
        if addNewUser:
            tm.addUser(image)
            new_user_added_event.set()
            addNewUser = False
        
        if homeSteering:
            home_steering_event.set()
            homeSteering = False
        
        image = cv2.resize(image, (650, 450))
        
        if image_to_process.get() is None:
            image.flags.writeable = False   # To pass by reference
            image_to_process.set(image)
            image.flags.writeable = True

        if (not authenticated_event.is_set()):
            cv2.putText(image, "Facial Recognition in Progress", (35, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            cv2.putText(image, "Please Look at the Camera", (115, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (50, 50, 255), 2)
                
        else:
            if (last_active_user.get() != active_user.get()):
                if (not calibrating_event.is_set()):
                    toggleCalibrate()

            pitch, yaw = pitch_yaw.get()

            cv2.putText(image, f"User: {active_user.get()}", (20, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.8, (40, 200, 13), 3)
            cv2.putText(image, "Control: Enabled" if control_wheelchair_event.is_set() else "Control: Disabled", (20, 420),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (40, 200, 13) if control_wheelchair_event.is_set() else (50, 50, 255), 2)

            if not calibrating_event.is_set():
                cv2.putText(image, "Pitch: " + str(int(pitch)), (460, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
                cv2.putText(image, "Yaw:  " + str(int(yaw)), (460, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
        
        if calibrating_event.is_set():
            cv2.putText(image, "Calibrating...", (425, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
            cv2.putText(
                image, calibration_instruction.get(), (75, 100), cv2.FONT_HERSHEY_COMPLEX, 1,
                    (0, 0, 255) if calibration_instruction.get() != "   Calibration Complete" else (40, 200, 13), 2)
            
        touchmenuImg = tm.getMenuImg()
        if not fr_ready_event.is_set():
            cv2.imshow("Wheelchair", loading_screen_img)
        else:
            cv2.imshow("Wheelchair", np.hstack((image, touchmenuImg)))
        
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q') or key == ord('Q') or key == 27:  # ESC or q to exit
            break   


    fr_process.terminate()
    fr_process.join()

    cm_process.terminate()
    cm_process.join()

    fm_process.terminate()
    fm_process.join()

    cv2.destroyAllWindows()
    exit()
