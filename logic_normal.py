# -*- coding: utf-8 -*-
#########################################################
# python
import os
import sys
import datetime
import traceback
import threading
import re
import subprocess
import shutil
import json
import ast
import time
import urllib
import rclone

# sjva 공용
from framework import app, db, scheduler, path_app_root, celery
from framework.job import Job
from framework.util import Util
from system.model import ModelSetting as SystemModelSetting
from framework.logger import get_logger


# 패키지
from .plugin import logger, package_name
from .model import ModelSetting, ModelItem

#torrent
import downloader
from downloader.logic_transmission import LogicTransmission
from downloader.logic_downloadstation import LogicDownloadStation
from downloader.logic_qbittorrent import LogicQbittorrent
from downloader.logic_aria2 import LogicAria2

#ktv
import bot_downloader_ktv
from bot_downloader_ktv.model import ModelSetting as KtvModelSetting, ModelBotDownloaderKtvItem as KtvModelBotDownloaderKtvItem

from subprocess import check_output

class LogicNormal(object):
    check_release = None

    @staticmethod
    @celery.task
    def scheduler_function():
        try:
            #logger.debug("파일정리 시작!")
            source_path = ModelSetting.get('source_path')
            download_path = ModelSetting.get('download_path')
            etc_path = ModelSetting.get('etc_path')
            move_type = ModelSetting.get('move_type')
            check_release = ModelSetting.get('check_release')
            LogicNormal.check_release = check_release
            fake_process = ModelSetting.get('fake_process')
            #logger.debug("source_path >> %s", source_path)
            #logger.debug("download_path >> %s", download_path)
            #logger.debug("etc_path >> %s", etc_path)
            if source_path != '' and download_path != '' and etc_path != '' and move_type != '':
                logger.debug("=========== SCRIPT START ===========")
                LogicNormal.init(source_path, download_path, etc_path)
                if move_type == '1':
                    LogicNormal.file_move_folder(source_path, download_path, etc_path)
                elif move_type == '2':
                    LogicNormal.file_move_day(source_path, download_path, etc_path)
                #파일 처리 완료후 FAKE 파일 있는지 검사
                if fake_process == 'True':
                    LogicNormal.init_torrent()
                    LogicNormal.retry_fake_file_download()
                logger.debug("=========== SCRIPT END ===========")
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())

    @staticmethod
    def init(source_path, download_path, etc_path):
        logger.debug("=========== init() START ===========")
        #초기 폴더 생성
        try:
            if not os.path.isdir(source_path): 
                os.makedirs(source_path)
        except OSError:
            logger.error("Error: Creating source_path." + source_path)
        try:
            if not os.path.isdir(download_path): 
                os.makedirs(download_path)
        except OSError:
            logger.error("Error: Creating download_path." + download_path)
        try:
            if not os.path.isdir(etc_path): 
                os.makedirs(etc_path)
        except OSError:
            logger.error("Error: Creating etc_path." + etc_path)
        logger.debug("=========== init() END ===========")

    #폴더별 처리
    @staticmethod
    def file_move_folder(source_path, download_path, etc_path):
        logger.debug("=========== file_move_folder() START ===========")
        
        #전달받은 path 경로에 / 없는 경우 예외처리
        if source_path.rfind("/")+1 != len(source_path):
            source_path = source_path+'/'

        if download_path.rfind("/")+1 != len(download_path):
            download_path = download_path+'/'

        if etc_path.rfind("/")+1 != len(etc_path):
            etc_path = etc_path+'/'

        ROOT_PATH = source_path
        FILE_PATH = download_path
        ETC_PATH = etc_path
       
        #폴더별 처리
        #검색 제외 리스트
        exclude = ['@eaDir']
        #이동할 파일 조회(파일, 폴더내 파일)
        fileList = os.listdir(FILE_PATH)

        for file in fileList:
            mvBool = True
            for ex in exclude:
                #시스템폴더 패스
                if ex == file:
                    mvBool = False
            #예외파일명 아니면 이동처리
            if mvBool:
                #파일이동처리
                logger.debug("target file name : %s", file)
                #프로그램명으로 폴더 생성
                directory = file.split('.')[0]
                directory = ROOT_PATH+directory
                try:
                    if not os.path.isdir(directory): 
                        os.makedirs(directory)
                except OSError:
                    logger.error("Error: Creating directory." + directory)
                
                #log("이동처리할 경로 : %s", FILE_PATH+file)
                #이동할 file명 조회(폴더인 경우 대비)
                if os.path.isfile(FILE_PATH+file):
                    logger.debug("target file path : %s", FILE_PATH+file)
                    fileName = file.split('.')[0]
                    #logger.debug("fileDate : %s", fileDate)
                    if os.path.isdir(ROOT_PATH+fileName):
                        logger.debug("### file_move_folder file process start ###")
                        logger.debug("move_file_name : %s", file)
                        logger.debug("move_path : %s", directory)
                        LogicNormal.move_file(FILE_PATH+file, directory+'/'+file)
                        logger.debug("### file_move_folder file complete ###")
                    else:
                        #etc 이동
                        LogicNormal.move_file(FILE_PATH+file, ETC_PATH+file)
                #폴더처리 시작
                elif os.path.isdir(FILE_PATH+file):
                    #폴더내 파일이동 후 삭제할 폴더
                    delete_path = FILE_PATH+file
                    logger.debug("delete_path : %s", delete_path)
                    #while start
                    while True:
                        filepath = LogicNormal.get_lastfile(FILE_PATH+file)
                        logger.debug("last_file_path : %s", filepath)
                        if filepath == '':
                            break
                        file_info = os.path.split(filepath)
                        file_name = file_info[1]
                        #폴더명과 파일명 다른경우 중지(광고URL)
                        logger.debug("file_name : %s, file : %s", file_name, file)
                        if file_name.upper().find(file.upper()) < 0:
                            break
                        #이름에 해당하는 폴더 있으면 이동
                        fileName = file_name.split('.')[0]
                        #logger.debug("fileDate : %s", fileDate)
                        logger.debug("ROOT_PATH+fileName : %s", ROOT_PATH+fileName)
                        if os.path.isdir(ROOT_PATH+fileName):
                            logger.debug("### file_move_folder folder process start ###")
                            logger.debug("move_file_name : %s", file)
                            logger.debug("move_path : %s", directory)
                            LogicNormal.move_file(filepath, directory+'/'+file_name)
                            logger.debug("### file_move_folder folder complete ###")
                        else:
                            #etc 이동
                            LogicNormal.move_file(FILE_PATH+file, ETC_PATH+file)
                    #while end
                    #폴더 삭제
                    if not delete_path == '':
                        logger.debug("delete_path : %s", delete_path)
                        LogicNormal.remove_dir(delete_path)
                #폴더 처리 완료
        logger.debug("=========== file_move_folder() END ===========")

    #날짜별 처리
    @staticmethod
    def file_move_day(source_path, download_path, etc_path):
        logger.debug("=========== file_move_day() START ===========")
       
        #전달받은 path 경로에 / 없는 경우 예외처리
        if source_path.rfind("/")+1 != len(source_path):
            source_path = source_path+'/'

        if download_path.rfind("/")+1 != len(download_path):
            download_path = download_path+'/'

        if etc_path.rfind("/")+1 != len(etc_path):
            etc_path = etc_path+'/'

        ROOT_PATH = source_path
        FILE_PATH = download_path
        ETC_PATH = etc_path
       
        #날짜별
        now = datetime.datetime.now()
        nowDate = now.strftime('%y%m%d')
        #logger.debug("nowDate : %s", nowDate)

        week = "("+LogicNormal.get_whichday(nowDate)+")"
        #logger.debug("요일 : %s", week)

        dirName = nowDate+week
        #logger.debug("dirName : %s", dirName)

        #날짜에 해당하는 폴더 없으면 생성
        directory = ROOT_PATH+dirName
        try:
            if not os.path.isdir(directory): 
                os.makedirs(directory)
        except OSError:
            logger.error("Error: Creating directory." + directory)
        
        #검색 제외 리스트
        exclude = ['@eaDir']
        #이동할 파일 조회(파일, 폴더내 파일)
        fileList = os.listdir(FILE_PATH)
          
        for file in fileList:
            mvBool = True
            for ex in exclude:
                #시스템폴더 패스
                if ex == file:
                    mvBool = False
            #예외파일명 아니면 당일날짜로 이동
            if mvBool:
                #파일이동처리
                #logger.debug("이동할 파일명 : %s", file)
                #이동할 file명 조회(폴더인 경우 대비)
                if os.path.isfile(FILE_PATH+file):
                    fileDate = file.split('.')[2]
                    #logger.debug("fileDate : %s", fileDate)
                    moveDir = ''
                    if len(fileDate) == 6:
                        #날짜에 해당하는 폴더 있으면 이동
                        checkWeek = "("+LogicNormal.get_whichday(fileDate)+")"
                        #logger.debug("checkWeek : %s", checkWeek)
                        moveDir = fileDate+checkWeek
                    
                    logger.debug("### file_move_day file process start ###")
                    if moveDir != '':
                        logger.debug("move_file_name : %s", file)
                        logger.debug("move_path : %s", moveDir)
                        #폴더 없으면 생성
                        if not os.path.isdir(ROOT_PATH+moveDir):
                            os.makedirs(ROOT_PATH+moveDir)
                        LogicNormal.move_file(FILE_PATH+file, ROOT_PATH+moveDir+'/'+file)
                    else:
                        #etc로 이동
                        logger.debug("target : %s", FILE_PATH+file)
                        logger.debug("result : %s", ETC_PATH+file)
                        LogicNormal.move_file(FILE_PATH+file, ETC_PATH+file)
                    logger.debug("### file_move_day file complete ###")
                #폴더처리 시작
                elif os.path.isdir(FILE_PATH+file):
                    #폴더내 파일이동 후 삭제할 폴더
                    delete_path = FILE_PATH+file
                    #logger.debug("delete_path : %s", delete_path)
                    #while start
                    while True:
                        filepath = LogicNormal.get_lastfile(FILE_PATH+file)
                        if filepath == '':
                            break
                        file_info = os.path.split(filepath)
                        file_name = file_info[1]
                        fileDate = file_name.split('.')[2]
                        #날짜에 해당하는 폴더 있으면 이동
                        moveDir = ''
                        if len(fileDate) == 6:
                            checkWeek = "("+LogicNormal.get_whichday(fileDate)+")"
                            #logger.debug("checkWeek : %s", checkWeek)
                            moveDir = fileDate+checkWeek
                            #logger.debug("moveDir : %s", moveDir)
                        
                        logger.debug("### file_move_day folder process start ###")
                        if moveDir != '':
                            logger.debug("move_file_name : %s", file_name)
                            logger.debug("move_path : %s", moveDir)
                            LogicNormal.move_file(filepath, ROOT_PATH+moveDir+'/'+file_name)
                        else:
                            #etc로 이동
                            logger.debug("target : %s", filepath)
                            logger.debug("result : %s", ETC_PATH+file_name)
                            LogicNormal.move_file(filepath, ETC_PATH+file_name)
                        logger.debug("### file_move_day folder complete ###")
                    #while end
                    #폴더 삭제
                    if not delete_path == '':
                        LogicNormal.remove_dir(delete_path)
                #폴더 처리 완료
        logger.debug("=========== file_move_day() END ===========")
    
    @staticmethod
    def remove_dir(path):
       shutil.rmtree(path)

    @staticmethod
    def get_lastfile(file):
       #파일이 나올때까지 반복
       full_filename = ""
       dirname = file
       for (path, dir, files) in os.walk(dirname):
          for filename in files:
             #synology 썸네일폴더 제외
             if path.find("@eaDir") < 0 :
                full_filename = path+'/'+filename
       return full_filename

    @staticmethod
    def get_whichday(date):
       r=['월','화','수','목','금','토','일']
       year = int(date[0:2])
       month = int(date[2:4])
       date = int(date[4:6])
       aday=datetime.date(year,month,date)
       bday=aday.weekday()
       return r[bday]

    @staticmethod
    def move_file(source, target):
        logger.debug("source : %s, target : %s", source, target)
        etc_path = ModelSetting.get('etc_path')
        if etc_path.rfind("/")+1 != len(etc_path):
            etc_path = etc_path+'/'

        #파일 이동전 가짜릴명 체크
        file_name = source.split("/")[-1]
        after_name = file_name
        
        #대상이 파일인 경우만 릴 검사
        encoder = ''
        if os.path.isfile(source):
            encoder = check_output('ffmpeg -i "'+source+'" 2>&1 | grep "encoder"', shell=True)
            encoder = encoder.split(':')[1]
            #릴재다운로드 + NEXT 릴인데 가짜릴 인 경우
            if LogicNormal.check_release == 'True' and file_name.upper().find("-NEXT") > -1 and encoder.find('MH ENCODER') < 0:
                logger.debug("release name NEXT, but encoder is not MH ENCODER")
                logger.debug("bug release file : %s", file_name)
                logger.debug("encoder : %s", encoder)
                #파일명 변환하여 이동
                after_name = file_name.replace("-NEXT", "-FAKE", 1).replace("-next", "-fake", 1)
                logger.debug("before name : %s, after name : %s", file_name, after_name)
                #파일 이동
                shutil.move(source, etc_path+after_name)
            else:
                #파일 이동
                shutil.move(source, target)


    @staticmethod
    def init_torrent():
        #torrent program init
        default_program = KtvModelSetting.get('torrent_program')
        if default_program == '0' and LogicTransmission.program is None:
            LogicTransmission.program_init()
        elif default_program == '1' and LogicDownloadStation.program is None:
            LogicDownloadStation.program_init()
        elif default_program == '2' and LogicQbittorrent.program is None:
            LogicQbittorrent.program_init()
        elif default_program == '3' and LogicAria2.program is None:
            LogicAria2.program_init()

    @staticmethod
    def retry_fake_file_download():
        logger.debug("retry_fake_file_download starting...")
        exclude = ['@eaDir']
        #FAKE 파일 조회
        etc_path = ModelSetting.get('etc_path')
        if etc_path.rfind("/")+1 != len(etc_path):
            etc_path = etc_path+'/'
        fileList = os.listdir(etc_path)
        for file in fileList:
            #FAKE 파일명으로 다운 재시도하여 RETRY 변경된 경우 해당 파일 삭제
            if file.upper().find('-RETRY') > -1:
                logger.debug("delete retry file name : %s", file)
                os.remove(etc_path+file)
            
            #FAKE 파일 재 요청
            if file.upper().find('-FAKE') > -1:
                #fake 파일명 체크
                logger.debug("fake file name : %s", file)
                #fake -> next
                search_name = file.replace("-FAKE", "-NEXT", 1).replace("-fake", "-next", 1)
                logger.debug("search_name : %s", search_name)

                query = db.session.query(KtvModelBotDownloaderKtvItem)
                query = query.filter(KtvModelBotDownloaderKtvItem.filename.like('%'+search_name+'%'))
                #아직 다운 안한 항목에 한함
                query = query.filter(KtvModelBotDownloaderKtvItem.download_status.like('False%'))
                #query = query.order_by(asc(KtvModelBotDownloaderKtvItem.created_time))

                count = query.count()
                if count > 0 :
                    #다운로드 추가 한 경우에만 이름 변경
                    downloader_item_id = ""
                    
                    #쿼리 실행 결과리스트
                    lists = query.all()
                    for data in lists:
                        logger.debug("item.id : %s", data.id)
                        item = db.session.query(KtvModelBotDownloaderKtvItem).filter_by(id=data.id).with_for_update().first()
                        default_program = KtvModelSetting.get('torrent_program')
                        logger.debug("item.magnet : %s", item.magnet)
                        logger.debug("default_program : %s", default_program)
                        logger.debug("torrent_program_path : %s", KtvModelSetting.get('path'))
                        
                        #add download
                        downloader_item_id = downloader.Logic.add_download2(item.magnet, default_program, KtvModelSetting.get('path'), request_type='bot_downloader_ktv', request_sub_type='')['downloader_item_id']
                        
                        item.downloader_item_id = downloader_item_id
                        logger.debug("downloader_item_id : %s", downloader_item_id)
                        #item.download_status = 'False'
                        #item.download_status = 'True_manual_%s_from_files_move_custom' % item.download_status
                        item.download_status = 'True_manual_%s_'+u'파일정리플러그인' % item.download_status
                        db.session.commit()
                    #재시도한 FAKE 의 경우 파일명 변경
                    after_name = file.replace("-FAKE", "-RETRY", 1).replace("-fake", "-retry", 1)
                    logger.debug("before name : %s, after name : %s", file, after_name)

                    #파일명 변경
                    if not downloader_item_id == '':
                        shutil.move(etc_path+file, etc_path+after_name)
        logger.debug("retry_fake_file_download finish...")