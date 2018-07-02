# 统计专用数据模块
from sqlalchemy import create_engine, func, ForeignKey, Column, Index
from sqlalchemy.types import String, Integer, Boolean, Float, Date,DateTime, Time
from sqlalchemy.dialects.mysql import INTEGER, TINYINT, YEAR
from dal.db_configs import Statistic_MapBase, statistic_DBSession
from dal.models import _CommonApi


class StatisticsDemand(Statistic_MapBase,_CommonApi):
    """要货单统计
    """
    __tablename__ = "statistics_demand"
    __table_args__=(
        Index('ix_shopid_goodsid_statisticyear_statisticweek','shop_id','goods_id','statistic_year','statistic_week',unique=True),
        Index('ix_shopid_goodsid_statisticyear_statisticmonth_statisticdate','shop_id','goods_id','statistic_year','statistic_month','statistic_date'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    statistic_type      = Column(TINYINT, nullable=False, default=0)                                # 统计类型 1: 日汇总 2: 周汇总　３：月汇总
    statistic_datetime      = Column(DateTime, nullable=False, default=func.now())                  # 统计起始时间，具体时间
    statistic_date      = Column(Date, nullable=False, default=func.curdate())                      # 统计起始日期，方便查询的
    statistic_year      = Column(Integer,nullable=False,default=0)                                  # 统计年份
    statistic_week      = Column(TINYINT,nullable=False,default=0)                                  # 统计周数
    statistic_month     = Column(TINYINT,nullable=False,default=0)                                  # 统计月数
    shop_id             = Column(Integer,nullable=False,default=0)                                  # 店铺id
    goods_id            =  Column(Integer,nullable=False,default=0)                                 # 商品id
    total_order_amount        = Column(Float, nullable=False, default=0)                            # 累计订货量
    total_wasted    = Column(Float, nullable=False, default=0)                                      # 累计昨日损耗
    total_sale      = Column(Float, nullable=False, default=0)                                      # 累计昨日销量
    total_arrival       = Column(Float, nullable=False, default=0)                                  # 累计到货
    average_purchase_price= Column(Integer, nullable=False, default=0)                              # 平均进价
    average_price         = Column(Integer, nullable=False, default=0)                              # 平均售价
    total_current_stock      = Column(Float, nullable=False, default=0)                             # 累计当前库存
    demand_count            = Column(Integer,nullable=False,default=0)                              # 累计数据来源于多少要货单，用于计算平均值
# 数据库初始化
def init_db_data():
    Statistic_MapBase.metadata.create_all()
    return True

