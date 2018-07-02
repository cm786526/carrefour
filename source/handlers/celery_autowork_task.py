import os,sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),"../")))
import requests
import datetime,time
from sqlalchemy import or_, func, and_, not_
import json
from celery import Celery
from celery.schedules import crontab
from celery import group
import dal.models as models
import dal.models_statistic as models_statistic
from dal.db_configs import (engine,DBSession,redis,statistic_DBSession)
from sqlalchemy.orm import (sessionmaker,scoped_session)
from handlers.base.pub_func import TimeFunc,NumFunc
from settings import (CELERY_BROKER,XINZHI_KEY,SMTP_SERVER,EMAIL_PASSWORD,\
    EMAIL_SENDER,EMAIL_RECEIVERS,EMAIL_SUBJECT,EMAIL_BODY)
from dal.area import dis_dict3 as area_dict
from dal.holiday_dict import holiday_dict
import xlwt
from xlwt import *
from xlrd import open_workbook
from xlutils.copy import copy
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
import smtplib
import handlers.base.pub_statistic as pub_statistic

AutoWork = Celery('auto_work', broker = CELERY_BROKER, backend = '')
AutoWork.conf.CELERY_TIMEZONE              = 'Asia/Shanghai'  # 时区
AutoWork.conf.CELERYD_CONCURRENCY          = 4                # 任务并发数
AutoWork.conf.CELERYD_TASK_SOFT_TIME_LIMIT = 300              # 任务超时时间
AutoWork.conf.CELERY_DISABLE_RATE_LIMITS   = True             # 任务频率限制开关

AutoWork.conf.CELERYBEAT_SCHEDULE = {
    'update_current_weather':{
        'task':'update_current_weather',
        'schedule':crontab(minute=0,hour=0),
        'options':{"queue":"auto_work"}
    },
    'export_statistic_data_only':{
        'task':'export_statistic_data_only',
        'schedule':crontab(minute=50,hour=23),
        'options':{"queue":"auto_work"}
    }
}

AutoWork.conf.CELERY_ROUTES = {                               # 任务调度队列
    "auto_work.export_statistic_data_and_mail": {"queue": "auto_work"},
}
scoped_DBSession = scoped_session(sessionmaker(autocommit=False, autoflush=False))
session=DBSession()
statistic_session=statistic_DBSession()
Shop=models.Shop
Goods=models.Goods

# @worker_init.connect
def initialize_session(signal,sender):
    scoped_DBSession.configure(bind=engine)


def get_goods_demand_by_shop(shop_id,date,statistic_type):
    """ 按天/周/月获取订货信息,分店铺展示
    """
    StatisticsDemand=models_statistic.StatisticsDemand
    filter_type=None
    if statistic_type==1:
        filter_type=StatisticsDemand.statistic_date==date
    elif statistic_type==2:
        filter_type=and_(StatisticsDemand.statistic_year==int(date.strftime("%Y")),\
                            StatisticsDemand.statistic_week==int(date.strftime("%W")))
    elif statistic_type==3:
        filter_type=and_(StatisticsDemand.statistic_year==int(date.strftime("%Y")),\
                            StatisticsDemand.statistic_month==int(date.strftime("%m")))
    all_demands=statistic_session.query(StatisticsDemand.total_order_amount,\
                                        StatisticsDemand.total_wasted,\
                                        StatisticsDemand.total_sale,\
                                        StatisticsDemand.total_arrival,\
                                        StatisticsDemand.average_purchase_price,\
                                        StatisticsDemand.average_price,\
                                        StatisticsDemand.total_current_stock,\
                                        StatisticsDemand.goods_id)\
                                  .filter(filter_type)\
                                  .filter_by(shop_id=shop_id,statistic_type=statistic_type)\
                                  .group_by(StatisticsDemand.goods_id)\
                                  .order_by(StatisticsDemand.goods_id)\
                                  .all()
    data_dict={}
    for each_demand in all_demands:
        average_purchase_price=NumFunc.check_float(each_demand[4]/100)
        average_price=NumFunc.check_float(each_demand[5]/100)
        each_goods_list=[each_demand[0],each_demand[1],each_demand[2],each_demand[3],\
        average_purchase_price,average_price,each_demand[6]]
        data_dict[each_demand[7]]=each_goods_list
    return data_dict

def export_goods(classify,all_shops,all_goods):
    """ 导出商品数据到 excel
    """
    def insert_excel(ws,inserted_row,inserted_list):
        for i in range(len(inserted_list)):
            ws.write(inserted_row,i,inserted_list[i])
    goods_classify=["fruit","vegetables"]
    path='../utils/exportdata/'+goods_classify[classify]+'/'
    today=datetime.date.today()
    weekday=today.weekday()
    week_list={0:"周一",1:"周二",2:"周三",3:"周四",4:"周五",5:"周六",6:"周日"}

    # 设计为每周只导出一个文件，对于每天更新的时候，首先找到本周所有日期对应的文件
    # 如果有，则编辑追加记录即可，但是如果还没有，则表明是第一次增加文件或者新的一
    #　周开始了，都需要重新添加一个文件
    dayscount = datetime.timedelta(days=today.isoweekday())
    dayfrom = today - dayscount + datetime.timedelta(days=1)
    dayto = today - dayscount + datetime.timedelta(days=7)
    file_name=str(dayfrom)+"~"+str(dayto)+"."+goods_classify[classify]
    wb=None
    exits=False
    try:
        rb = open_workbook(path+file_name+'.xls')
        wb = copy(rb)
        exits=True
    except:
        wb=xlwt.Workbook()
    # 代表当前sheet的索引
    shop_count=0
    for each_shop in all_shops:
        ws=None
        if not exits:
            # 计算总量的时候需要覆写，所以加上cell_overwrite_ok=True
            ws=wb.add_sheet(each_shop.shop_name.replace("/",""),cell_overwrite_ok=True)
            # 初始化表头
            ws.write_merge(0,1,0,2,"从"+str(dayfrom)+"至"+str(dayto))
            for i in range(7):
                ws.write_merge(0,1,3+i*7,3+(i+1)*7-1,week_list.get(i,"周一"))
                tr_head=['库存','定价','售价','订货','到货','损耗','销量']
                for j in range(len(tr_head)):
                    ws.write(2,3+i*7+j,tr_head[j])
            ws.write_merge(0,1,52,54,"总计")
            tr_head = ['单品编号','中文品名','单位']
            insert_excel(ws,2,tr_head)
            tr_head=['总到货','总损耗','总销量']
            for j in range(len(tr_head)):
                    ws.write(2,52+j,tr_head[j])
        else:
            # 如果是打开的文件，则需要考虑当前店铺数量增加了，所以需要增加新的sheet以及对应表头
            if shop_count>=len(rb.sheets()):
                ws=wb.add_sheet(each_shop.shop_name.replace("/",""),cell_overwrite_ok=True)
                # 初始化表头
                ws.write_merge(0,1,0,2,"从"+str(dayfrom)+"至"+str(dayto),style)
                for i in range(7):
                    ws.write_merge(0,1,3+i*7,3+(i+1)*7-1,week_list.get(i,"周一"))
                    tr_head=['库存','定价','售价','订货','到货','损耗','销量']
                    for j in range(len(tr_head)):
                        ws.write(2,3+i*7+j,tr_head[j])
                ws.write_merge(0,1,52,54,"总计")
                tr_head = ['单品编号','中文品名','单位']
                insert_excel(ws,2,tr_head)
                tr_head=['总到货','总损耗','总销量']
                for j in range(len(tr_head)):
                        ws.write(2,52+j,tr_head[j])
            else:
                ws=wb.get_sheet(shop_count)
                shop_count+=1

        # 添加每种水果按天统计的数据
        # 获取当天的统计数据
        data_dict=get_goods_demand_by_shop(each_shop.id,today,1)

        # 初始化每种商品基本信息
        j=0
        for each_goods in all_goods:
            # 本来 如果是新建的时候 需要填写商品信息 如果是打开的，则不需要填写，但是考虑到新增加商品
            # 所以，仍然需要覆写，增加商品对应的行数
            ws.write(3+j,0,each_goods.goods_code)
            ws.write(3+j,1,each_goods.goods_name)
            ws.write(3+j,2,each_goods.unit_text)
            statistic_info = data_dict.get(each_goods.id)
            for k in range(7):
                if statistic_info:
                    ws.write(3+j,3+weekday*7+k,statistic_info[k])
                else:
                    ws.write(3+j,3+weekday*7+k,0)
            j+=1

        # 获取当周的统计数据
        data_dict=get_goods_demand_by_shop(each_shop.id,today,2)
        # 初始化每种商品的统计数据
        j=0
        for each_goods in all_goods:
            statistic_info = data_dict.get(each_goods.id)
            if statistic_info:
                ws.write(3+j,52,statistic_info[3])
                ws.write(3+j,53,statistic_info[1])
                ws.write(3+j,54,statistic_info[2])
            else:
                ws.write(3+j,52,0)
                ws.write(3+j,53,0)
                ws.write(3+j,54,0)
            j+=1
    wb.save(path+file_name+'.xls')
    return True


@AutoWork.task(bind=True,name="update_current_weather")
def update_current_weather(self):
    """ 每天早上凌晨自动更新天气信息，保存到数据库
    """
    Shop=models.Shop
    HistoryWeatherRecord=models.HistoryWeatherRecord
    all_citys=scoped_DBSession.query(Shop.shop_city).distinct().all()
    all_citys_code=[]
    for city in all_citys:
        all_citys_code.append(city.shop_city)
    current_date=datetime.date.today()
    current_weekday=current_date.weekday()
    holiday="无"
    if str(current_date) in holiday_dict:
        holiday=holiday_dict[current_date]
    elif current_weekday in [5,6]:
        holiday="周末"
    city_list=area_dict["city_list"]
    country_list=area_dict["country_list"]
    failed_count=0

    # 遍历每个城市，并添加天气信息
    for city_code in all_citys_code:
        city_name=""
        str_city_code=str(city_code)
        if str_city_code in city_list:
            city_name=city_list[str_city_code]
        elif str_city_code in country_list:
            city_name=country_list[str_city_code]
        # 请求天气数据
        result=requests.get('https://api.seniverse.com/v3/weather/daily.json?key='+\
                            XINZHI_KEY+'&location='+city_name+'&language=zh-Hans&unit=c&start=0&days=１')
        if result.status_code != 200:
            failed_count+=1
            continue
        result=json.loads(result.content.decode("utf-8"))
        result=result["results"][0]["daily"][0]
        new_weather = HistoryWeatherRecord(city_code=city_code,\
                                           city_name=city_name,\
                                           create_date=current_date,\
                                           low_temperature=result["low"],\
                                           high_temperature=result["high"],\
                                           weather=result["text_day"],\
                                           week_day=current_weekday,\
                                           holiday=holiday)
        scoped_DBSession.add(new_weather)
    scoped_DBSession.commit()
    scoped_DBSession.close()
    print("共计%d个城市或者区域的天气信息没有找到"%failed_count)
    return True


def send_email(email_receivers):
    """ 发送邮件
    """
    goods_classify=["fruit","vegetables"]
    path_base='../utils/exportdata/'
    path_fruit=path_base+goods_classify[0]+'/'
    path_vegetables=path_base+goods_classify[1]+'/'
    today=datetime.date.today()
    weekday=today.weekday()
    dayscount = datetime.timedelta(days=today.isoweekday())
    dayfrom = today - dayscount + datetime.timedelta(days=1)
    dayto = today - dayscount + datetime.timedelta(days=7)
    file_name_fruit=str(dayfrom)+"~"+str(dayto)+"."+goods_classify[0]
    file_name_vegetables=str(dayfrom)+"~"+str(dayto)+"."+goods_classify[1]
    file_fruit=path_fruit+file_name_fruit+'.xls'
    file_vegetables=path_vegetables+file_name_vegetables+'.xls'

    smtpserver = SMTP_SERVER
    password = EMAIL_PASSWORD
    sender = EMAIL_SENDER
    receivers = ','.join(email_receivers)

    # 如名字所示： Multipart就是多个部分
    msg = MIMEMultipart()
    msg['Subject'] = EMAIL_SUBJECT
    msg['From'] = sender
    msg['To'] = receivers

    # 下面是文字部分，也就是纯文本
    puretext = MIMEText(EMAIL_BODY)
    msg.attach(puretext)

    # 下面是附件部分
    # xlsx类型的附件
    xlsxpart_fruit = MIMEApplication(open(file_fruit, 'rb').read())
    xlsxpart_fruit.add_header('Content-Disposition', 'attachment', filename=file_name_fruit+'.xls')
    xlsxpart_vegetables = MIMEApplication(open(file_vegetables, 'rb').read())
    xlsxpart_vegetables.add_header('Content-Disposition', 'attachment', filename=file_name_vegetables+'.xls')
    msg.attach(xlsxpart_fruit)
    msg.attach(xlsxpart_vegetables)
    try:
        smtpObj = smtplib.SMTP_SSL()
        smtpObj.connect(smtpserver,465) # SMTP协议默认端口是25  但是如果是SSL 则是465 或者587
        smtpObj.login(sender,password)
        smtpObj.sendmail(sender,receivers,msg.as_string())
        smtpObj.quit()
        return True
    except smtplib.SMTPException as e:
        print(e.message)
        print("发送邮件失败")
        return False

@AutoWork.task(bind=True,name="export_statistic_data_only")
def export_statistic_data_only(self):
    """ 每天晚上23点50分导出订货统计信息
    """
    # 导出数据之前　一定要更新一波数据
    pub_statistic.Statistic.demand_statistic(session,statistic_session)

    market_id=1
    all_shops=session.query(Shop).filter_by(market_id=market_id).order_by(Shop.id).all()
    all_goods=session.query(Goods).filter_by(market_id=market_id).order_by(Goods.id)
    print("正在导出水果统计excel......")
    fruit_goods=all_goods.filter_by(classify=1).all()
    if export_goods(0,all_shops,fruit_goods):
        print("成功导出水果统计excel")
    print("正在导出蔬菜统计excel......")
    vegetables_goods=all_goods.filter_by(classify=2).all()
    if export_goods(1,all_shops,vegetables_goods):
        print("成功导出蔬菜统计excel")
    # 关闭session
    session.close()
    statistic_session.close()


@AutoWork.task(bind=True,name="auto_work.export_statistic_data_and_mail")
def export_statistic_data_and_mail(self,email_receivers,market_id):
    """ 管理员手动导出订货统计信息 并且发送邮件
    """
    # 导出数据之前　一定要更新一波数据
    pub_statistic.Statistic.demand_statistic(session,statistic_session)

    all_shops=session.query(Shop).filter_by(market_id=market_id).order_by(Shop.id).all()
    all_goods=session.query(Goods).filter_by(market_id=market_id).order_by(Goods.id)
    print("正在导出水果统计excel......")
    fruit_goods=all_goods.filter_by(classify=1).all()
    if export_goods(0,all_shops,fruit_goods):
        print("成功导出水果统计excel")
    print("正在导出蔬菜统计excel......")
    vegetables_goods=all_goods.filter_by(classify=2).all()
    if export_goods(1,all_shops,vegetables_goods):
        print("成功导出蔬菜统计excel")
    # 关闭session
    session.close()
    statistic_session.close()
    # 发送邮件
    if send_email(email_receivers):
        print("发送邮件成功")
