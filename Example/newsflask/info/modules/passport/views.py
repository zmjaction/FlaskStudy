# encoding: utf-8
import random
import re
from datetime import datetime

from flask import request, abort, make_response, json, jsonify, session

from info.libs.yuntongxun.sms import CCP
from info.models import User
from info.utils.response_code import RET

__author__ = 'action'

from . import passpot_blu
from info.utils.captcha.captcha import captcha
from info import redis_store, db
from info import constants
from flask import current_app


@passpot_blu.route('/register', methods=["POST"])
def register():
    """
    注册的逻辑
    1. 获取参数
    2. 校验参数
    3. 取到服务器保存的真实的短信验证码内容
    4. 校验用户输入的短信验证码内容和真实验证码内容是否一致
    5. 如果一致 初始化User模型, 并且赋值属性
    6. 将user 模型添加到数据库
    7. 返回响应
    :return:
    """
    # 1. 获取参数
    params_dict = request.json
    mobile = params_dict.get("mobile")
    smscode = params_dict.get("smscode")
    password = params_dict.get("password")

    # 2. 校验参数
    if not all([mobile, smscode, password]):
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    # 校验手机号是否正确
    if not re.match('1[35678]\\d{9}', mobile):
        return jsonify(errno=RET.PARAMERR, errmsg="手机号格式不正确")
    # 3. 取到服务器保存的真实的短信验证码内容
    try:
        real_sms_code = redis_store.get("SMS_" + mobile)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="参数查询错误")
    if not real_sms_code:
        return jsonify(errno=RET.NODATA, errmsg="验证码已过期")

    # 4. 校验用户输入的短信验证码内容和真实验证码内容是否一致
    if real_sms_code != smscode:
        return jsonify(errno=RET.DATAERR, errmsg="验证码输入错误")

    # 5. 如果一致 初始化User模型, 并且赋值属性
    user = User()
    user.mobile = mobile
    # 暂时没有昵称 使用手机号代替
    user.nick_name = mobile
    # 记录用户最后一次登录的时间
    user.last_login = datetime.now()
    # TODO 对密码做处理

    # 6. 将user 模型添加到数据库
    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="数据保存失败")

    # 往session中保存数据表示已经登录
    session['user_id'] = user.id
    session['mobile'] = user.mobile
    session['nick_name'] = user.nick_name

    # 7.返回响应
    return jsonify(errno=RET.OK, errmsg='发送成功')


@passpot_blu.route('/sms_code', methods=['POST'])
def send_sms_code():
    """
    发送短信验证码的逻辑实现
    1. 获取参数: 手机号, 图片验证码内容,图片验证码的编号(随机值)
    2. 校验参数(参数是否符合规则,判断是否有值)
    3. 先从redis中取出真实的验证码内容
    4. 与用户的验证码用户进行对比,如果对比不一致,那么返回验证码输入错误
    5. 如果一致, 生成手机验证码的内容(随机数据)
    6. 发送短信验证码
    7. 告知发送的结果
    :return:
    """
    # '{"mobiel": "18811111111", "image_code": "AAAA", "image_code_id": "u23jksdhjfkjh2jh4jhdsj"}' 获取到的值示例
    # 1. 获取参数: 手机号, 图片验证码内容,图片验证码的编号(随机值)
    # params_dict = json.loads(request.data) 这两种写法一致,转字典
    params_dict = request.json

    mobile = params_dict.get('mobile')
    image_code = params_dict.get('image_code')
    image_code_id = params_dict.get('image_code_id')

    # 2. 校验参数(参数是否符合规则,判断是否有值)
    # 判断参数是否有值
    if not all([mobile, image_code, image_code_id]):
        return jsonify(errno=RET.PARAMERR, errmsg='手机号格式不正确')
    # 校验手机号是否正确
    if not re.match('1[35678]\\d{9}', mobile):
        return jsonify(errno=RET.PARAMERR, errmsg="手机号格式不正确")
    # 3. 先从redis中取出真实的验证码内容
    try:
        real_image_code = redis_store.get("ImageCodeId_" + image_code_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='数据查询失败')
    if not real_image_code:
        return jsonify(errno=RET.NODATA, errmsg='图片验证码已过期')
    # 4. 与用户的验证码用户进行对比,如果对比不一致,那么返回验证码输入错误
    if real_image_code.upper() != image_code.upper():
        return jsonify(errno=RET.DATAERR, errmsg='验证码输入错误')

    # 5. 如果一致, 生成手机验证码的内容(随机数据)
    # 随机数字,保证数字长度为6位, 不够在前边补上0
    sms_code_str = "%06d" % random.randint(0, 999999)
    current_app.logger.debug("短信验证码内容是:%s" % sms_code_str)
    # 6. 发送短信验证码
    result = CCP().send_template_sms(mobile, [sms_code_str, constants.SMS_CODE_REDIS_EXPIRES / 60], "1")
    if result != 0:
        # 代表发送不成功
        return jsonify(errno=RET.THIRDERR, errmsg='发送短信失败')
    # 保存手机验证码内容到redis
    try:
        redis_store.set("SMS_" + mobile, sms_code_str, constants.SMS_CODE_REDIS_EXPIRES)
    except Exception as e:
        return jsonify(errno=RET.DBERR, errmsg='数据保存失败')

    # 7. 告知发送结果
    return jsonify(errno=RET.OK, errmsg='发送成功')


@passpot_blu.route('/image_code')
def get_image_code():
    """
    生成图片验证码并返回
    1. 取到参数
    2. 判断参数是否有值
    3. 生成图片验证码
    4. 保存图片验证码文字内容到redis中
    5. 返回验证码图片
    :return:
    """
    # 1. 取到参数
    # args: 取到url中? 后面的参数
    image_code_id = request.args.get('imageCodeId', None)
    # 2.判断是否有值
    # abort 异常主动抛出
    if not image_code_id:
        return abort(403)
    # 3. 生成图片验证码
    name, text, image = captcha.generate_captcha()
    # 4. 保存图片验证码文字内容到redis中
    # set 也可以设置过期时间
    # "ImageCodeId_"+image_code_id 随机值作为redis的key
    #  constants.IMAGE_CODE_REDIS_EXPIRES 设置过期时间
    try:
        redis_store.set("ImageCodeId_" + image_code_id, text, constants.IMAGE_CODE_REDIS_EXPIRES)
    except Exception as e:
        current_app.logger.error(e)
        abort(500)  # 如果出现错误就是服务器错误
    # 5. 返回验证码图片
    response = make_response(image)
    # 设置数据的类型,以便浏览器更加只能是被其实什么类型的数据
    response.headers['Content-Type'] = 'image/jpg'
    return response
