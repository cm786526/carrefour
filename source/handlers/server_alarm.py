import json
import hashlib
import requests
import datetime,time
import re

from sqlalchemy import func

import dal.models as models
import dal.models_statistic as models_statistic
from dal.db_configs import redis
from handlers.base.pub_log import log_msg,log_msg_dict

class ServerAlarm():
    """处理服务器报警
    """
    @classmethod
    def send_server_error(cls,slave_session,request_uri,**kwargs):
        """服务器出现500错误时发送模板消息提醒
            服务器错误使用redis缓存72小时
            错误字典使用错误内容生成的md5值做key
            查看路径使用key参数用于查看不同的错误
        """
        import traceback
        import time
        import json
        from urllib import parse
        from handlers.base.pub_func import UrlShorten
        from dal.db_configs import redis
        server_error_messsage = traceback.format_exception(*kwargs["exc_info"])
        intro     = '采购助手服务器500报错'
        content   = '出错地址 '+str(request_uri)
        time_now  = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        describe  = '请尽快检查错误并修正'
        hour_now  = int(datetime.datetime.now().strftime('%H'))
        timestamp = int(time.time())
        to_users  = [104,105,156,1085]
        acs = slave_session.query(models.Accountinfo.wx_openid).filter(models.Accountinfo.id.in_(to_users)).all()
        server_error_messsage = json.dumps(server_error_messsage)
        errror_key = UrlShorten.get_hex(server_error_messsage)
        server_error  = "Server_Error:%s"%errror_key
        server_error_times = "Server_Error_Times:%s"%errror_key
        if redis.get(server_error):
            redis.incr(server_error_times)
        else:
            redis.set(server_error,server_error_messsage,72*60*60)
            redis.set(server_error_times,1,72*60*60)
            for account in acs:
                try:
                    if hour_now in [4,5,6,7]:
                        countdown = (9-hour_now)*3600-1800
                    else:
                        countdown = 0
                    # 暂时使用的
                    cls.send_servererror_msg(account[0],"https://pf.senguo.cc/super/servererror/"+str(errror_key),intro,content,time_now,describe)
                except:
                    pass

    @classmethod
    def send_servererror_msg(self, touser, link, intro, content, time_now, describe):
        """ 发送服务器报错模版消息
        """
        import requests
        import json
        from handlers.base.pub_wx_web import WxOauth2
        try:
            access_token = WxOauth2.get_client_access_token()
            template_id = '42lkJUEd39CGC61rC024kIzVA2CfGjiC7cGu3sBSs7U'
            postdata = {
                'touser'      : touser,
                'template_id' : template_id,
                'url'         : link,
                'topcolor'    : '#FF0000',
                "data" : {
                    "first"    : {"value":intro+'\n',"color":"#44b549"},
                    "keyword1" : {"value":content,"color":"#173177"},
                    "keyword2" : {"value":time_now,"color":"#173177"},
                    "remark"   : {"value":'\n'+describe,"color":"#173177"},
                }
            }
            res = requests.post(WxOauth2.template_msg_url.format(access_token=access_token),data = json.dumps(postdata),headers = {"Content-Type":"application/x-www-form-urlencoded","Connection":"close"})
            try:
                data = json.loads(res.content.decode("ascii"))
            except:
                print("[TempMsg]Server error message send to %s failed: %s" % (touser,res))
                return res
            if data["errcode"] != 0:
                print("[TempMsg]Server error message send to %s failed: %s" % (touser,data))
                return data["errmsg"]
            return True
        except Exception as exc:
            raise self.retry(exc=exc)