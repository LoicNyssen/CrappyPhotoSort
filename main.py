import json
import os
import pathlib

import cv2
import shutil
import filecmp
import bcolors

import numpy as np
from string import Template
from datetime import datetime
from PIL import Image, ExifTags

import tkinter
from tkinter import messagebox


SOURCE = '/Users/loicnyssen/Temp'
NAS = '/Volumes/Shoebox/Archive'

FILE_TYPES = ['.jpg', '.jpeg']
DELETE_FILES = ['Screenshot']

FOLDER_FORMAT = "$year/$month"
FILE_FORMAT = "${year}${month}${day}_${time}${extra}.jpg"

IMG_MAX_WIDTH, IMG_MAX_HEIGHT = 800, 1000


class Mode:
    TESTING = 0
    PRODUCTION = 1


class Verbose:
    YES = 0
    NO = 1

class Action:
    MOVE = 0
    COPY = 1


class PhotoSorter:
    def __init__(self, source: str, destination: str, mode: int = Mode.PRODUCTION, action: int = Action.MOVE, verbose: int = Verbose.YES):
        self._tk = tkinter.Tk()
        self._tk.withdraw()

        self._source = source
        self._destination = destination

        self._mode = mode
        self._action = action
        self._verbose = verbose
        self._look_for_json = False
        self._use_file_name = False

        self._console = self.Console()

        self._get_photos()

    def _move(self, source: str, destination: str):
        path = os.path.dirname(os.path.abspath(destination))
        if not os.path.exists(path):
            self._console.msg(f"Creating {path}")
            if self._mode == Mode.PRODUCTION:
                os.makedirs(path)

        match self._action:
            case Action.MOVE:
                self._console.msg(f"Moving {source} to {destination}")
                if self._mode == Mode.PRODUCTION:
                    shutil.move(source, destination)
            case Action.COPY:
                self._console.msg(f"Copying {source} to {destination}")
                if self._mode == Mode.PRODUCTION:
                    shutil.copy(source, destination)

    def _delete(self, source: str):
        self._console.msg(f"Moving {os.path.basename(source)} to trash")

        save_file = f"{os.path.dirname(__file__)}/Trash/{os.path.basename(source)}"
        if os.path.exists(save_file):
            save_file = self._increment_file_name(f"{os.path.dirname(__file__)}/Trash/", os.path.basename(source))
            self._console.wrn(f"File already exists, saving as {os.path.basename(save_file)}")
        if self._mode == Mode.PRODUCTION:
            self._move(source, save_file)

    def _increment_file_name(self, destination: str, file_name: str) -> str:
        i = 1
        while True:
            new_name = f"{destination}/{file_name[:-4]}_{i}.jpg"
            if not os.path.exists(new_name):
                break
            i += 1
        return new_name

    def _get_photos(self) -> None:
        self._console.msg('Getting photos')

        for root, dirs, files in os.walk(SOURCE):
            for file in files:
                if file.lower().endswith(tuple(FILE_TYPES)):
                    if any(ele in file.lower() for ele in [x.lower() for x in DELETE_FILES]):
                        self._console.wrn(f'Found Ignore file {os.path.basename(file)}')
                        self._delete(os.path.join(root, file))
                        continue
                    try:
                        self._process_photo(os.path.join(root, file))
                    except self.NoTimeData:
                        self._console.wrn(f'No timestamp found for {file}')
                    # except Exception as e:
                    #     self._console.err(f'An error occurred while processing {file} :: {e}\n{e.__traceback__}')

    def _process_photo(self, photo: str) -> None:
        exif_data = Image.open(photo)._getexif()
        timestamp = None

        if exif_data:
            for tag, value in exif_data.items():
                if ExifTags.TAGS.get(tag, tag) == "DateTimeOriginal":
                    timestamp = value
                    break

        if not timestamp:
            if self._look_for_json:
                taken_timestamp = self._get_date_from_json(photo)
                if taken_timestamp:
                    timestamp = self._get_date_from_json(photo)

                    if self._verbose == Verbose.YES:
                        if not self._keep_photo(photo):
                            return
                else:
                    raise self.NoTimeData
            elif self._use_file_name:
                print(f"{os.path.basename(photo)[0:15]}")
                exit(0)
            else:
                raise self.NoTimeData

        date, time = timestamp.split(" ")

        year, month, day = date.split(":")
        time = time.replace(":", "")

        self._save_path = Template(FOLDER_FORMAT).substitute(year=year, month=month)
        file_name = Template(FILE_FORMAT).substitute(year=year, month=month, day=day, time=time, extra="")

        self._move_photo(photo, f"{self._destination}/{self._save_path}", file_name)

    def _find_json(self, photo: str):
        json_file = f"{photo}.json"
        if os.path.exists(json_file):
            self._console.msg(f"Found json for {os.path.basename(photo)} :: {os.path.basename(json_file)}")
            return json_file
        else:
            extension_length = len(pathlib.Path(photo).suffix)
            for i in range(0, 10):
                chop = int(extension_length + i)
                json_file = f"{photo[:-chop]}.json"
                if os.path.exists(json_file):
                    self._console.msg(f"Found json for {os.path.basename(photo)} :: {os.path.basename(json_file)}")
                    return json_file

        self._console.wrn(f"No json found for {os.path.basename(photo)}")
        return None

    def _get_date_from_json(self, photo: str):
        json_file = self._find_json(photo)

        if json_file:
            with open(json_file, 'r') as json_data:
                data = json.load(json_data)
                date = datetime.fromtimestamp(int(data['photoTakenTime']['timestamp']))
                return date.strftime('%Y:%m:%d %H:%M:%S')
        else:
            return None

    def _move_photo(self, photo: str, save_path: str, file_name: str) -> None:
        if os.path.exists(f"{save_path}/{file_name}"):
            self._compare_photos(photo, f"{save_path}/{file_name}")
        else:
            self._move(photo, f"{save_path}/{file_name}")

    def _compare_photos(self, duplicate: str, existing: str) -> None:
        if not filecmp.cmp(duplicate, existing, shallow=False):
            img_existing = cv2.imread(existing)
            img_duplicate = cv2.imread(duplicate)

            self._console.msg(f"Duplicate found, {duplicate} will be deleted")
            self._display_photo_compare(img_existing, img_duplicate, existing, duplicate)

        else:
            self._console.msg(f"File contents are exact!, {duplicate} will be deleted")
            self._delete(duplicate)

    @staticmethod
    def _resize_photo(photo):
        f1 = IMG_MAX_WIDTH / photo.shape[1]
        f2 = IMG_MAX_HEIGHT / photo.shape[0]

        f = min(f1, f2)  # resizing factor
        dim = (int(photo.shape[1] * f), int(photo.shape[0] * f))

        return cv2.resize(photo, dim)

    @staticmethod
    def _open_window(title, photo, x_offset=0, y_offset=0):
        cv2.namedWindow(title)  # Create a named window
        cv2.moveWindow(title, 0 + x_offset, 0 + y_offset)  # Move it to (x,y)
        cv2.imshow(title, photo)

    def _keep_photo(self, photo):
        print(photo)
        img = cv2.imread(photo)

        img_resized = self._resize_photo(img)
        title = f"{os.path.basename(photo)} has no exif timestamp, please confirm"
        keep = None
        while True:
            self._open_window(title, img_resized)

            match cv2.waitKey(0):
                case 107:
                    self._console.msg(f"Keeping {title}")
                    keep = True
                    break
                case 100:
                    self._console.msg(f"Deleting {title}")
                    self._delete(photo)
                    keep = False
                    break
                case _:
                    continue

        cv2.destroyAllWindows()
        cv2.waitKey(1)

        return keep

    def _display_photo_compare(self, left, right, existing, duplicate) -> None:
        name_existing = os.path.basename(existing)
        name_duplicate = os.path.basename(duplicate)

        left_resized = self._resize_photo(left)
        right_resized = self._resize_photo(right)

        while True:
            self._open_window(f"Left - {name_existing} - {os.stat(existing).st_size / (1024 * 1024)}", left_resized)
            self._open_window(f"Right - {name_duplicate} - {os.stat(duplicate).st_size / (1024 * 1024)}", right_resized, x_offset=left_resized.shape[1])

            match cv2.waitKey(0):
                case 100:
                    # ans = messagebox.askquestion(
                    #     'Keep Left',
                    #     f'Are you sure you want to keep {name_existing}, and delete {name_duplicate}?',
                    #     icon='warning')
                    # if ans == 'yes':
                        self._console.msg(f"Keeping {name_existing}")
                        self._delete(duplicate)
                        break

                case 108:
                    # ans = messagebox.askquestion(
                    #     'Keep Left',
                    #     f'Are you sure you want to keep {name_existing}, and delete {name_duplicate}?',
                    #     icon='warning')
                    # if ans == 'yes':
                        self._console.msg(f"Keeping {name_existing}")
                        self._delete(duplicate)
                        break
                case 114:
                    # ans = messagebox.askquestion(
                    #     'Keep Right',
                    #     f'Are you sure you want to keep {name_duplicate}, and delete {name_existing}?',
                    #     icon='warning')
                    # if ans == 'yes':
                        self._console.msg(f"Keeping {name_duplicate}")
                        self._delete(existing)
                        # replace existing with duplicate
                        self._move(duplicate, existing)
                        break
                case 98:
                    # ans = messagebox.askquestion(
                    #     'Keep Both',
                    #     f'Are you sure you want to keep both {name_existing} and {name_duplicate}?')
                    # if ans == 'yes':
                        self._console.msg(f"Keeping both {name_existing} and {name_duplicate}")
                        self._move(duplicate, self._increment_file_name(f"{self._destination}/{self._save_path}", name_existing))
                        break
                case 27:
                    print("esc")
                    self._console.msg(f"Leaving {name_existing} and {name_duplicate}")
                    break
                case _:
                    continue

        cv2.destroyAllWindows()
        cv2.waitKey(1)

    class NoTimeData(Exception):
        pass

    class Console:
        prefix = f"[PhotoSorter] {datetime.now().strftime('%H:%M:%S')} :: "
        suffix = ""

        def _format(self, message: str):
            return f"{self.prefix}{message}{self.suffix}"

        def msg(self, message: str):
            print(bcolors.OK + self._format(message) + bcolors.ENDC)

        def wrn(self, message: str):
            print(bcolors.WARN + self._format(message) + bcolors.ENDC)

        def err(self, message: str):
            print(bcolors.FAIL + self._format(message) + bcolors.ENDC)


if __name__ == '__main__':
    PhotoSorter(SOURCE, NAS)
