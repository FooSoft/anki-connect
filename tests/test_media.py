import base64
import os.path

from conftest import ac


FILENAME = "_test.txt"
BASE64_DATA_1 = base64.b64encode(b"test 1").decode("ascii")
BASE64_DATA_2 = base64.b64encode(b"test 2").decode("ascii")


def store_one_media_file():
    return ac.storeMediaFile(filename=FILENAME, data=BASE64_DATA_1)


def store_two_media_files():
    filename_1 = ac.storeMediaFile(filename=FILENAME, data=BASE64_DATA_1)
    filename_2 = ac.storeMediaFile(filename=FILENAME, data=BASE64_DATA_2,
                                   deleteExisting=False)
    return filename_1, filename_2


##############################################################################


def test_storeMediaFile_one_file(session_with_profile_loaded):
    filename_1 = store_one_media_file()
    assert FILENAME == filename_1


def test_storeMediaFile_two_files_with_the_same_name(session_with_profile_loaded):
    filename_1, filename_2 = store_two_media_files()
    assert FILENAME == filename_1 != filename_2


def test_retrieveMediaFile(session_with_profile_loaded):
    store_one_media_file()
    result = ac.retrieveMediaFile(filename=FILENAME)
    assert result == BASE64_DATA_1


def test_getMediaFilesNames(session_with_profile_loaded):
    filenames = store_two_media_files()
    result = ac.getMediaFilesNames(pattern="_tes*.txt")
    assert {*filenames} == {*result}


def test_deleteMediaFile(session_with_profile_loaded):
    filename_1, filename_2 = store_two_media_files()
    ac.deleteMediaFile(filename=filename_1)
    assert ac.retrieveMediaFile(filename=filename_1) is False
    assert ac.getMediaFilesNames(pattern="_tes*.txt") == [filename_2]


def test_getMediaDirPath(session_with_profile_loaded):
    assert os.path.isdir(ac.getMediaDirPath())
