import tornado.web
import os,sys
from sqlalchemy import or_, func,and_
import datetime
from dal.db_configs import redis
from handlers.base.pub_web import _AccountBaseHandler,GlobalBaseHandler
from handlers.base.pub_func import TimeFunc,NumFunc
from libs.msgverify import gen_msg_token,check_msg_token
import dal.models as models
import dal.models_statistic as models_statistic
from libs.senguo_encrypt import SimpleEncrypt
from tornado.websocket import WebSocketHandler
import urllib
import logging
import json
import xlrd
import xlwt
import re
from  dal.carrefour_region_dict import store_dict


class LoginVerifyCode(_AccountBaseHandler):
    """未登录用户获取短信验证码，用于注册或登录"""
    def prepare(self):
        """屏蔽登录保护"""
        pass

    @_AccountBaseHandler.check_arguments("action:str", "phone:str")
    def post(self):
        action = self.args["action"]
        phone = self.args["phone"]
        if len(phone) != 11:
            return self.send_fail("请填写正确的手机号")
        if action not in models.VerifyCodeUse.login_verify_code_use:
            if action not in models.VerifyCodeUse.operation_verify_code_use:
                return self.send_fail("invalid action")
        # 发送验证码
        result = gen_msg_token(phone, action)
        if result is True:
            return self.send_success()
        else:
            return self.send_fail(result)


class Profile(_AccountBaseHandler):
    """个人中心
    """
    @tornado.web.authenticated
    def prepare(self):
        """
            所有用户都必须要有手机号,没有手机号需重定向至手机号绑定页面
        """
        if not self.current_user.phone:
            return self.redirect(self.reverse_url("PhoneBind"))

    def get(self):
        #获取个人信息
        return self.render("login/login.html")

    @_AccountBaseHandler.check_arguments("action:str")
    def post(self):
        action=self.args["action"]
        if action=="get_profile":
            return self.get_profile()
        elif action=="set_password":
            return self.set_password()
        elif action=="modify_password":
            return self.set_password()
        elif action=="modify_phone":
            return self.modify_phone()
        elif action=="change_role":
            return self.change_role()
        else:
            return self.send_fail(404)

    def get_profile(self):
        """ 获取个人信息
        """
        session=self.session
        current_user_id=self.current_user.id
        AccountInfo=models.Accountinfo
        account_info=session.query(AccountInfo)\
                            .filter_by(id=current_user_id)\
                            .first()
        account_dict={
            "id":account_info.id,
            "staff_id":account_info.id,
            "phone":account_info.phone,
            "realname":account_info.nickname,
            "headimgurl":account_info.headimgurl,
            "sex_text":account_info.sex_text
        }
        return self.send_success(account_dict=account_dict)

    @_AccountBaseHandler.check_arguments("password:str")
    def set_password(self):
        """ 设置密码
        """
        password=self.args["password"]
        password=SimpleEncrypt.encrypt(password)
        session=self.session
        current_user_id=self.current_user.id
        AccountInfo=models.Accountinfo
        account_info=session.query(AccountInfo)\
                            .filter_by(id=current_user_id)\
                            .first()
        account_info.password=password
        session.commit()
        return self.send_success()

    @_AccountBaseHandler.check_arguments("phone:str","code:str")
    def modify_phone(self):
        """ 修改手机号
        """
        phone=self.args["phone"]
        code=self.args["code"]
        session=self.session
        current_user_id=self.current_user.id
        AccountInfo=models.Accountinfo
        check_msg_res = check_msg_token(phone, code, use="bind")
        if not check_msg_res:
            return self.send_fail("验证码过期或者不正确")
        account_info=session.query(AccountInfo)\
                            .filter_by(id=current_user_id)\
                            .first()
        account_info.phone=phone
        session.commit()
        return self.send_success()

    @_AccountBaseHandler.check_arguments("target:str")
    def change_role(self):
        """切换角色
        """
        target=self.args["target"]
        # 判断用户是否可以切换
        current_user_id=self.current_user.id
        session=self.session
        HireLink=models.HireLink
        max_staff=session.query(func.max(HireLink.active_admin),\
                                func.max(HireLink.active_recorder))\
                        .filter_by(staff_id=current_user_id)\
                        .first()
        if target=="admin":
            if max_staff[0]:
                return self.send_success(next_url=self.reverse_url("shopmanage"))
            else:
                return self.send_fail("您不是管理员，不能切换到管理端")
        elif target=="recorder":
            if max_staff[1]:
                return self.send_success(next_url=self.reverse_url("recordergoodsmanage"))
            else:
                return self.send_fail("您不是录入员，不能切换到录入端")
        else:
            return self.send_fail(404)


class GoodsDetail(_AccountBaseHandler):
    """商品详情
    """

    @_AccountBaseHandler.check_arguments("action?:str","goods_id:int")
    def get(self):
        goods_id=self.args.get("goods_id",0)
        action=self.args.get("action","")
        current_goods=self.session.query(models.Goods)\
                          .filter_by(id=goods_id)\
                          .first()
        goods_info={}
        if current_goods:
            goods_info={
                "goods_id":goods_id,
                "goods_name":current_goods.goods_name,
                "unit_text":current_goods.unit_text
            }

        if action=="get_subbranch_detail":
            return self.render("admin/subbranch-detail.html",goods_info=goods_info)
        else:
            return self.render("recorder/goods-detail.html",goods_info=goods_info)

    @_AccountBaseHandler.check_arguments("action:str")
    def post(self):
        action=self.args["action"]

        # 需要首先更新统计数据库
        session = self.session
        statistic_session = self.statistic_session
        update_key = "carrefour_update_key"         # 更新标志

        # 有更新标志位才进行统计更新，否则每一个小时才更新一次
        import handlers.base.pub_statistic as pub_statistic
        if redis.setnx(update_key,1):
            redis.expire(update_key,5*60)
            pub_statistic.Statistic.demand_statistic(session,statistic_session)

        if action=="get_details":
            return self.get_details()
        elif action=="get_goods_demand_by_date":
            return self.get_goods_demand_by_date()
        elif action=="get_goods_demand_by_week":
            return self.get_goods_demand_by_week()
        elif action=="get_goods_demand_by_month":
            return self.get_goods_demand_by_month()
        elif action=="get_goods_demand_by_shop":
            # 分店铺统计按天/周/月的某种水果的要货信息
            return self.get_goods_demand_by_shop()
        elif action=="get_goods_demand_for_recent":
            # 获取最近多少天/周/月的某种水果的要货信息
            return self.get_goods_demand_for_recent()
        else:
            return self.send_fail(404)

    @_AccountBaseHandler.check_arguments("goods_id:str","date:str")
    def get_details(self):
        """ 根据商品id 查询要货详细数据
        """
        goods_id=self.args.get("goods_id",0)
        date=self.args["date"]
        start_datetime = datetime.datetime.strptime(date, "%Y-%m-%d")
        end_datetime = start_datetime + datetime.timedelta(days=1)
        session = self.session
        Demand = models.Demand
        Accountinfo = models.Accountinfo
        Goods = models.Goods
        all_demands=session.query(Demand,Accountinfo,Goods)\
                            .join(Accountinfo,Demand.opretor_id==Accountinfo.id)\
                            .join(Goods,Demand.shop_id==Goods.id)\
                            .filter(Demand.create_date>=start_datetime,\
                                    Demand.create_date<=end_datetime)\
                            .filter_by(Demand.goods_id==goods_id)\
                            .order_by(Demand.create_date.desc())\
                            .all()
        data_list=[]
        for each_demand,account_info,goods in all_demands:
            each_goods_dict ={
                "id":each_demand.id,\
                "goods_id":each_demand.goods_id,\
                "goods_name":goods.goods_name,\
                "unit":goods.unit_text,\
                "order_amount":each_demand.order_amount,\
                "yesterday_wasted":each_demand.yesterday_wasted,\
                "create_date":str(each_demand.create_date).replace(each_demand.create_date.strftime('%Y-%m-%d'),""),\
                "yesterday_sale":each_demand.yesterday_sale,\
                "today_arrival":each_demand.today_arrival,\
                "today_purchase_price":each_demand.today_purchase_price/100,\
                "today_price":each_demand.today_price/100,\
                "current_stock":each_demand.current_stock,\
                "opretor_name":account_info.nickname
            }
            data_list.append(each_goods_dict)
        return self.send_success(data_list=data_list)

    def get_goods_demand_base(self,goods_id,date,statistic_type):
        """ 按天/周/月获取订货信息，其他任何获取信息都可以调用这个方法
            statistic_type 1:按天 2：按周 3：按月
        """
        statistic_session=self.statistic_session
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
        each_demand=statistic_session.query(func.sum(StatisticsDemand.total_order_amount),\
                                            func.sum(StatisticsDemand.total_wasted),\
                                            func.sum(StatisticsDemand.total_sale),\
                                            func.sum(StatisticsDemand.total_arrival),\
                                            func.sum(StatisticsDemand.average_purchase_price),\
                                            func.sum(StatisticsDemand.average_price),\
                                            func.sum(StatisticsDemand.total_current_stock),\
                                            func.count(StatisticsDemand.id))\
                                     .filter(filter_type)\
                                     .filter_by(goods_id=goods_id,\
                                                statistic_type=statistic_type)\
                                     .first()
        each_goods_dict={
            "date_text":date,\
            "total_order_amount":0,\
            "total_yesterday_wasted":0,\
            "total_yesterday_sale":0,\
            "total_today_arrival":0,\
            "average_purchase_price":0,\
            "average_price":0,\
            "total_current_stock":0
        }
        demand_count=each_demand[7]
        if  demand_count:
            average_purchase_price=NumFunc.check_float(each_demand[4]/demand_count/100)
            average_price=NumFunc.check_float(each_demand[5]/demand_count/100)
            each_goods_dict ={
                "date_text":date,\
                "total_order_amount":NumFunc.check_float(each_demand[0]),\
                "total_yesterday_wasted":NumFunc.check_float(each_demand[1]),\
                "total_yesterday_sale":NumFunc.check_float(each_demand[2]),\
                "total_today_arrival":NumFunc.check_float(each_demand[3]),\
                "average_purchase_price":average_purchase_price,\
                "average_price":average_price,\
                "total_current_stock":NumFunc.check_float(each_demand[6])
            }
        return each_goods_dict

    @_AccountBaseHandler.check_arguments("goods_id:int")
    def get_goods_demand_by_date(self):
        """按天获取订货信息 获取最近三天的统计数据
        """
        goods_id=self.args.get("goods_id",0)
        today=datetime.date.today()
        yesterday_date=today+datetime.timedelta(days=-1)
        pre_yesterday_date=today+datetime.timedelta(days=-2)

        # 查询今天，昨天，前天三天的记录
        data_list=[]
        today_dict=self.get_goods_demand_base(goods_id,today,1)
        today_dict["date_text"]="今天"
        data_list.append(today_dict)

        yesterday_dict=self.get_goods_demand_base(goods_id,yesterday_date,1)
        yesterday_dict["date_text"]="昨天"
        data_list.append(yesterday_dict)

        pre_dict=self.get_goods_demand_base(goods_id,pre_yesterday_date,1)
        pre_dict["date_text"]=pre_yesterday_date.strftime("%m-%d")
        data_list.append(pre_dict)
        return self.send_success(data_list=data_list)


    @_AccountBaseHandler.check_arguments("goods_id:int")
    def get_goods_demand_by_week(self):
        """ 按周获取订货信息,查询最近三周的统计数据
        """
        goods_id=self.args.get("goods_id",0)
        today=datetime.date.today()
        this_week_start_date,_=TimeFunc.get_week_start_end(today)
        last_week_start_date =this_week_start_date+datetime.timedelta(days=-7)
        last_week_end_date=last_week_start_date+datetime.timedelta(days=6)
        pre_week_start_date=this_week_start_date+datetime.timedelta(days=-14)
        pre_week_end_date=pre_week_start_date+datetime.timedelta(days=6)

        # 查询这周，上周，上上周的记录
        data_list=[]
        this_week=this_week_start_date.strftime("%m-%d")+"~"+today.strftime("%m-%d")
        this_week_dict=self.get_goods_demand_base(goods_id,this_week_start_date,2)
        this_week_dict["date_text"]=this_week
        data_list.append(this_week_dict)

        last_week=last_week_start_date.strftime("%m-%d")+"~"+last_week_end_date.strftime("%m-%d")
        last_week_dict=self.get_goods_demand_base(goods_id,last_week_start_date,2)
        last_week_dict["date_text"]=last_week
        data_list.append(last_week_dict)

        pre_week=pre_week_start_date.strftime("%m-%d")+"~"+pre_week_end_date.strftime("%m-%d")
        pre_week_dict=self.get_goods_demand_base(goods_id,pre_week_start_date,2)
        pre_week_dict["date_text"]=pre_week
        data_list.append(pre_week_dict)

        return self.send_success(data_list=data_list)

    @_AccountBaseHandler.check_arguments("goods_id:int")
    def get_goods_demand_by_month(self):
        """ 按月获取订货信息,查询最近三个月的统计数据
        """
        goods_id=self.args.get("goods_id",0)
        today=datetime.date.today()
        this_month_start_date=datetime.date(today.year, today.month,1)
        last_month_end_date=this_month_start_date+datetime.timedelta(days=-1)
        last_month_start_date =datetime.date(last_month_end_date.year, last_month_end_date.month,1)
        pre_month_end_date=last_month_start_date+datetime.timedelta(days=-1)
        pre_month_start_date=datetime.date(pre_month_end_date.year, pre_month_end_date.month,1)

        # 查询这月，上月，上上月的记录
        data_list=[]
        this_month=this_month_start_date.strftime("%m-%d")+"~"+today.strftime("%m-%d")
        this_month_dict=self.get_goods_demand_base(goods_id,this_month_start_date,3)
        this_month_dict["date_text"]=this_month
        data_list.append(this_month_dict)

        last_month=last_month_start_date.strftime("%m-%d")+"~"+last_month_end_date.strftime("%m-%d")
        last_month_dict=self.get_goods_demand_base(goods_id,last_month_start_date,3)
        last_month_dict["date_text"]=last_month
        data_list.append(last_month_dict)

        pre_month=pre_month_start_date.strftime("%m-%d")+"~"+pre_month_end_date.strftime("%m-%d")
        pre_month_dict=self.get_goods_demand_base(goods_id,pre_month_start_date,3)
        pre_month_dict["date_text"]=pre_month
        data_list.append(pre_month_dict)

        return self.send_success(data_list=data_list)

    @_AccountBaseHandler.check_arguments("goods_id:int","date:str","statistic_type:int")
    def get_goods_demand_by_shop(self):
        """ 按天/周/月获取订货信息,分店铺展示
            statistic_type 1:按天 2：按周 3：按月
        """
        goods_id=self.args.get("goods_id",0)
        date=self.args["date"]
        statistic_type=self.args.get("statistic_type",0)
        date=datetime.datetime.strptime(date,"%Y-%m-%d")
        statistic_session=self.statistic_session
        StatisticsDemand=models_statistic.StatisticsDemand
        Shop=models.Shop
        filter_type=None
        if statistic_type==1:
            filter_type=StatisticsDemand.statistic_date==date
        elif statistic_type==2:
            filter_type=and_(StatisticsDemand.statistic_year==int(date.strftime("%Y")),\
                                StatisticsDemand.statistic_week==int(date.strftime("%W")))
        elif statistic_type==3:
            filter_type=and_(StatisticsDemand.statistic_year==int(date.strftime("%Y")),\
                                StatisticsDemand.statistic_month==int(date.strftime("%m")))
        all_demands=statistic_session.query(func.sum(StatisticsDemand.total_order_amount),\
                                            func.sum(StatisticsDemand.total_wasted),\
                                            func.sum(StatisticsDemand.total_sale),\
                                            func.sum(StatisticsDemand.total_arrival),\
                                            func.sum(StatisticsDemand.average_purchase_price),\
                                            func.sum(StatisticsDemand.average_price),\
                                            func.sum(StatisticsDemand.total_current_stock),\
                                            func.count(StatisticsDemand.id),\
                                            StatisticsDemand.shop_id)\
                                     .filter(filter_type)\
                                     .filter_by(goods_id=goods_id,statistic_type=statistic_type)\
                                     .group_by(StatisticsDemand.shop_id)\
                                     .order_by(StatisticsDemand.shop_id)\
                                     .all()
        data_list=[]
        shop_ids=[]
        for each_demand in all_demands:
            demand_count=each_demand[7]
            if not demand_count:
                continue
            shop_ids.append(each_demand[8])
            demand_count=each_demand[7]
            average_purchase_price=NumFunc.check_float(each_demand[4]/demand_count/100)
            average_price=NumFunc.check_float(each_demand[5]/demand_count/100)
            each_goods_dict ={
                "shop_text":"",\
                "total_order_amount":NumFunc.check_float(each_demand[0]),\
                "total_yesterday_wasted":NumFunc.check_float(each_demand[1]),\
                "total_yesterday_sale":NumFunc.check_float(each_demand[2]),\
                "total_today_arrival":NumFunc.check_float(each_demand[3]),\
                "average_purchase_price":average_purchase_price,\
                "average_price":average_price,\
                "total_current_stock":NumFunc.check_float(each_demand[6])
            }
            data_list.append(each_goods_dict)

        # 给每条数据补充店铺信息
        all_shops=self.session.query(Shop.shop_name)\
                                .filter(Shop.id.in_(shop_ids))\
                                .order_by(Shop.id)\
                                .all()
        for each_shop in all_shops:
            index=all_shops.index(each_shop)
            data_list[index]["shop_text"]=each_shop[0]

        # 添加商品详情
        current_goods=self.session.query(models.Goods)\
                                    .filter_by(id=goods_id)\
                                    .first()
        goods_info={
            "goods_id":goods_id,
            "goods_name":current_goods.goods_name,
            "unit_text":current_goods.unit_text
        }
        self.send_success(data_list=data_list,goods_info=goods_info)


    @_AccountBaseHandler.check_arguments("goods_id:int","statistic_type:int","number:int")
    def get_goods_demand_for_recent(self):
        """ 获取最近多少天/周/月的统计数据
            numner 天/周/月 的数量
        """
        statistic_session=self.statistic_session
        StatisticsDemand=models_statistic.StatisticsDemand
        goods_id=self.args.get("goods_id",0)
        today=datetime.date.today()
        begin_date=today
        statistic_type=self.args.get("statistic_type",0)
        number=self.args.get("number",0)
        data_list=[]
        order_type=None
        group_type=None
        if statistic_type==1:
            order_type=StatisticsDemand.statistic_date
            begin_date=today+datetime.timedelta(days=-number+1)
        elif statistic_type==2:
            order_type=StatisticsDemand.statistic_year+StatisticsDemand.statistic_week
            group_type=StatisticsDemand.statistic_year+StatisticsDemand.statistic_week
            begin_date=today+datetime.timedelta(days=-(number-1)*7-today.isoweekday()+1)
        elif statistic_type==3:
            order_type=StatisticsDemand.statistic_year+StatisticsDemand.statistic_month
            group_type=StatisticsDemand.statistic_year+StatisticsDemand.statistic_month
            # 需要保正
            if number>12:
                self.send_fail("不能查看超过最近12个月以上")
            if today.month-number<0:
                begin_date=datetime.date(today.year-1,today.month-number+13,1)
            else:
                begin_date=datetime.date(today.year,today.month-number+1,1)

        all_demands=statistic_session.query(func.sum(StatisticsDemand.total_order_amount),\
                                            func.sum(StatisticsDemand.total_wasted),\
                                            func.sum(StatisticsDemand.total_sale),\
                                            func.sum(StatisticsDemand.total_arrival),\
                                            func.sum(StatisticsDemand.average_purchase_price),\
                                            func.sum(StatisticsDemand.average_price),\
                                            func.sum(StatisticsDemand.total_current_stock),\
                                            func.count(StatisticsDemand.id),\
                                            func.min(StatisticsDemand.statistic_date))\
                                    .filter(StatisticsDemand.statistic_date>=begin_date,\
                                            StatisticsDemand.statistic_date<=today)\
                                    .filter_by(goods_id=goods_id,statistic_type=statistic_type)\
                                    .order_by(order_type)\
                                    .group_by(group_type)\
                                    .all()
        data_list=[]
        each_date_range=[]
        next_date=begin_date
        # 初始化列表
        for n in range(0,number):
            default_dict={
                "total_order_amount":0,\
                "total_yesterday_wasted":0,\
                "total_yesterday_sale":0,\
                "total_today_arrival":0,\
                "average_purchase_price":0,\
                "average_price":0,\
                "total_current_stock":0
            }
            each_date_range.append(next_date)
            if statistic_type==1:
                next_date+=datetime.timedelta(days=1)
            elif statistic_type==2:
                next_date+=datetime.timedelta(days=7)
            elif statistic_type==3:
                if next_date.month+1>12:
                    next_date=datetime.date(next_date.year+1,next_date.month-11,1)
                else:
                    next_date=datetime.date(next_date.year,next_date.month+1,1)
            data_list.append(default_dict)

        #　对应时间有数据的就根据index补充上
        for each_demand in all_demands:
            index=-1
            demand_count=each_demand[7]
            if not demand_count:
                continue
            statistic_date=each_demand[8]
            for n in range(0,number):
                if n+1<number:
                    if statistic_date>=each_date_range[n] and statistic_date<each_date_range[n+1]:
                        index=n
                        break
                else:
                    if statistic_date>=each_date_range[n]:
                        index=n
            average_purchase_price=NumFunc.check_float(each_demand[4]/demand_count/100)
            average_price=NumFunc.check_float(each_demand[5]/demand_count/100)
            each_goods_dict ={
                "total_order_amount":NumFunc.check_float(each_demand[0]),\
                "total_yesterday_wasted":NumFunc.check_float(each_demand[1]),\
                "total_yesterday_sale":NumFunc.check_float(each_demand[2]),\
                "total_today_arrival":NumFunc.check_float(each_demand[3]),\
                "average_purchase_price":average_purchase_price,\
                "average_price":average_price,\
                "total_current_stock":NumFunc.check_float(each_demand[6])}
            data_list[index]=each_goods_dict
        self.send_success(data_list=data_list)


class Weather(GlobalBaseHandler):

    """天气相关的接口
       暂时未用到
    """
    def get(self):
        return self.render("login/login.html")

    def post(self):
        return self.send_success()

    #根据日期获取天气
    def get_weather_info_by_date():
        return self.send_success()


class CheckUpdate(tornado.web.RequestHandler):
    """检查app更新
    """
    def post(self):
        return self.write(redis.get("carrefour_update_info"))


class UpdateWebSocket(WebSocketHandler,_AccountBaseHandler):
    """websocket代替轮询获取更新的数据
    """
    # 保存连接的管理员，用于后续推送消息
    all_shop_admins = {}
    all_shop_recorders= {}
    def open(self):
        # print("new　client opened")
        # 根据cookie判断用户当前在管理端还是录入端
        user_type = self.get_cookie('user_type')
        HireLink=models.HireLink
        if not self.current_user:
            pass
        current_user_id=self.current_user.id
        all_shop_admins=UpdateWebSocket.all_shop_admins
        all_shop_recorders=UpdateWebSocket.all_shop_recorders
        session=self.session
        if user_type=="admin":
            # 判断连接的管理员所在店铺id
            all_shops=session.query(HireLink.shop_id)\
                                .filter_by(staff_id=current_user_id,\
                                            active_admin=1)\
                                .all()
            for each_shop in all_shops:
                _id=str(each_shop[0])
                if _id in all_shop_admins:
                    all_shop_admins[_id].append(self)
                else:
                    all_shop_admins[_id]=[self]
        elif user_type=="recorder":
            # 判断连接的录入员所在的店铺id
            all_shops=session.query(HireLink.shop_id)\
                                .filter_by(staff_id=current_user_id,\
                                            active_recorder=1)\
                                .all()
            for each_shop in all_shops:
                _id=str(each_shop[0])
                if _id in all_shop_recorders:
                    all_shop_recorders[_id].append(self)
                else:
                    all_shop_recorders[_id]=[self]

    def on_close(self):
        # print("one client closed")
        for value in UpdateWebSocket.all_shop_admins.values():
            if self in value:
                value.remove(self)

    # 录入员录入完成之后发送消息告诉管理员
    @classmethod
    def send_demand_updates(cls,message):
        logging.info("sending message to %d admins", len(cls.all_shop_admins))
        all_admins=[]
        shop_id=str(message["shop_id"])
        if shop_id in UpdateWebSocket.all_shop_admins:
            all_admins=UpdateWebSocket.all_shop_admins[shop_id]
        for _admin in all_admins:
            try:
                _admin.write_message(message)
            except:
                logging.error("Error sending message", exc_info=True)

    # 管理员修改预订系数之后告诉录入员
    @classmethod
    def send_ratio_updates(cls,message):
        logging.info("sending message to %d recorders", len(cls.all_shop_recorders))
        all_recorders=[]
        shop_id=str(message["shop_id"])
        if shop_id in UpdateWebSocket.all_shop_recorders:
            all_recorders=UpdateWebSocket.all_shop_recorders[shop_id]
        for _recorder in all_recorders:
            try:
                _recorder.write_message(message)
            except:
                logging.error("Error sending message", exc_info=True)

    def on_message(self,message):
        # 接收客户端发来的消息
        logging.info("got message %r", message)

    def check_origin(self, origin):
        parsed_origin = urllib.parse.urlparse(origin)
        return parsed_origin.netloc.index(".senguo.cc")!=-1

class FileUploadHandler(GlobalBaseHandler):
    def get(self):
        return self.render("recorder/upload-file.html")

    def post(self):
        file_metas = self.request.files.get('file', None)  # 提取表单中‘name’为‘file’的文件元数据
        if not file_metas:
            return  self.send_fail("缺少文件")
        # 获取上级目录
        path_base=os.path.join(os.path.dirname(__file__),"../utils/uploadfile/")
        # 判断文件夹是否存在，没有则创建
        if not os.path.exists(path_base):
            os.makedirs(path_base)
        for meta in file_metas:
            filename = (meta['filename'])
            file_path = path_base+filename
            # 判断文件是否存在
            if os.path.exists(file_path):
                return self.send_fail("文件已经上传，请勿重复操作")
            with open(file_path, 'wb') as new_file:
                new_file.write(meta['body'])
        # 解析上传的excel文件，更新数据库中的数据
        return self.resolve_excel_update_goods(file_path)

    def resolve_excel_update_goods(self,file_path):
        Goods=models.Goods
        ShopGoods=models.ShopGoods
        Shop=models.Shop
        session=self.session
        xlrd.Book.encoding = "gbk"
        xls_workbook = xlrd.open_workbook(file_path)
        table = xls_workbook.sheets()[0]
        nrows = table.nrows
        discount_type=['normal','dm','lf','wk']
        update_goods_info={}
        update_shop_goods_info={}
        print(0,"开始解析excel",datetime.datetime.now())
        for i in range(2, nrows):
            row = table.row_values(i)
            store_code,dept,item_code,cn_name,en_name,capacity,pack,prom_type,ratio,pp,sp=row

            # 判断店铺号
            try:
                store_code=str(int(store_code))
                shop_id = store_dict.get(store_code,0)
                if not shop_id:
                    os.remove(file_path)
                    return self.send_fail("更新失败，第{}行门店编号不存在".format(i))
            except:
                os.remove(file_path)
                return self.send_fail("更新失败，第{}行门店编号格式不正确".format(i))

            # 判断部门号
            try:
                dept=str(int(dept))
            except:
                os.remove(file_path)
                return self.send_fail("更新失败，第{}行部门编号格式不正确".format(i))

            # 判断商品编号
            try:
                item_code=str(int(item_code))
                if len(item_code)!=8:
                    os.remove(file_path)
                    return self.send_fail("更新失败，第{}行货品编号格式不正确".format(i))
            except:
                os.remove(file_path)
                return self.send_fail("更新失败，第{}行货品编号格式不正确".format(i))

            # 判断计量方式
            if capacity.lower().find("kg") !=-1 :
                new_unit =1
            else:
                new_unit =2

            #　判断折扣方式
            discount=discount_type.index(prom_type.lower())
            if discount==-1:
                discount=0

            # 判断预定系数是否正确
            try:
                if ratio!="":
                    reserve_ratio=float(ratio)
                else:
                    if discount:
                        reserve_ratio=2.0
                    else:
                        reserve_ratio=None
            except:
                os.remove(file_path)
                return self.send_fail("更新失败，第{}行预定系数格式不正确".format(i))

            # 判断价格是否正确
            try:
                today_purchase_price=int(pp*100)
            except:
                os.remove(file_path)
                return self.send_fail("更新失败，第{}行进价格式不正确".format(i))
            try:
                today_sale_price=int(sp*100)
            except:
                os.remove(file_path)
                return self.send_fail("更新失败，第{}行售价格式不正确".format(i))

            # 判断商品分类
            if item_code[2:4]=='60':
                    classify=2
            else:
                classify=1
            # 搜集信息
            if item_code in update_goods_info:
                print(item_code,"重复")
            update_goods_info[item_code]=[cn_name,en_name,new_unit,classify,pack]
            if shop_id not in update_shop_goods_info:
                update_shop_goods_info[shop_id]={}
            update_shop_goods_info[shop_id][item_code]=[dept,discount,reserve_ratio,today_purchase_price,today_sale_price]
        print(1,"完成解析excel",datetime.datetime.now())
        # 更新旧的商品信息
        old_goods_codes=[]
        goods_id_code_dict={}
        goods_code_id_dict={}
        all_exist_goods=session.query(Goods).filter_by(market_id=1).with_lockmode("update").all()
        count=0
        for item in all_exist_goods:
            code=item.goods_code
            if code in update_goods_info:
                goods_info=update_goods_info[code]
                item.goods_name=goods_info[0]
                item.goods_name_en=goods_info[1]
                item.unit=goods_info[2]
                item.classify=goods_info[3]
                item.pack=goods_info[4]
                old_goods_codes.append(code)
                goods_id_code_dict[item.id]=code
                goods_code_id_dict[code]=item.id
                count+=1
        print(2,"更新了%s种商品信息"%count,datetime.datetime.now())
        # 增加新的商品信息
        count=0
        for code in update_goods_info:
            if code not in old_goods_codes:
                goods_info=update_goods_info[code]
                item=Goods(goods_code=code,market_id=1)
                item.goods_name=goods_info[0]
                item.goods_name_en=goods_info[1]
                item.unit=goods_info[2]
                item.classify=goods_info[3]
                item.pack=goods_info[4]
                session.add(item)
                session.flush()
                goods_id_code_dict[item.id]=code
                goods_code_id_dict[code]=item.id
                count+=1
        print(3,"添加了%s种商品信息"%count,datetime.datetime.now())

        # 更新旧的店铺商品信息
        old_shop_goods_codes={}
        all_shop_goods=session.query(ShopGoods)\
                                .join(Goods,ShopGoods.goods_id==Goods.id)\
                                .join(Shop,ShopGoods.shop_id==Shop.id)\
                                .filter(Goods.market_id==1,\
                                        Shop.market_id==1)\
                                .with_lockmode("update")\
                                .all()
        count=0
        for item in all_shop_goods:
            s_id=item.shop_id
            g_id=item.goods_id
            if s_id in update_shop_goods_info:
                if g_id in goods_id_code_dict:
                    g_code=goods_id_code_dict[g_id]
                    s_g_info=update_shop_goods_info[s_id][g_code]
                    item.dept=s_g_info[0]
                    item.discount=s_g_info[1]
                    if s_g_info[2]:
                        item.reserve_ratio=s_g_info[2]
                    item.today_purchase_price=s_g_info[3]
                    item.today_sale_price=s_g_info[4]
                    if s_id not in old_shop_goods_codes:
                        old_shop_goods_codes[s_id]=[]
                    old_shop_goods_codes[s_id].append(g_code)
                    count+=1
                    item.status=1
                else:
                    item.status=-1

        print(4,"更新了%s种店铺-商品信息"%count,datetime.datetime.now())

        count=0
        # 增加新的店铺商品记录
        for s_id in update_shop_goods_info:
            for g_code in update_shop_goods_info[s_id]:
                if not old_shop_goods_codes or g_code not in old_shop_goods_codes[s_id]:
                    s_g_info=update_shop_goods_info[s_id][g_code]
                    g_id=goods_code_id_dict[g_code]
                    item=ShopGoods(shop_id=s_id,goods_id=g_id)
                    item.dept=s_g_info[0]
                    item.discount=s_g_info[1]
                    if s_g_info[2]:
                        item.reserve_ratio=s_g_info[2]
                    item.today_purchase_price=s_g_info[3]
                    item.today_sale_price=s_g_info[4]
                    session.add(item)
                    count+=1
        print(5,"增加了%s种店铺-商品信息"%count,datetime.datetime.now())
        session.commit()
        # 删除文件
        os.remove(file_path)
        return self.send_success()

class FileDownloadHandler(GlobalBaseHandler):
    @GlobalBaseHandler.check_arguments("filename:str")
    def get(self):
        filename=self.args["filename"]
        path_base=os.path.abspath(os.path.join(os.path.dirname(__file__),"../utils/uploadfile/"))
        file_path = path_base + filename
        # 判断文件是否存在
        if os.path.exists(file_path):
            return self.send_fail("文件不存在")
        new_file=open(file_path, 'wb')
        with open(file_path, 'rb') as target_file:          # 读取文件内容
            data = target_file.read()
        # response = self.response(data, content_type='application/octet-stream') # 响应指明类型，写入内容
        self.set_header("Content-Type","application/octet-stream")
        return self.write(data)
