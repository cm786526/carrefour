$(document).ready(function($) {
    $('#file_upload').uploadifive(
        {
            buttonText    : '',
            width: '120px',
            uploadScript  : '/fileupload',
            uploadLimit     : 10,
            multi    :     false,
            fileSizeLimit   : '10MB',
            'fileObjName' : 'file',
            'removeCompleted' : false,
            'fileType':'*.xlsx,*.xls',
            'formData':{
                'action':''
            },
            'onAddQueueItem' : function(file){
                var fileName = file.name;
                var reg=/^(.*)\.(xlsx)$/;
                var reg2=/^(.*)\.(xls)$/;
                if(!reg.test(fileName)&&!reg2.test(fileName)){
                    Tip("上传文件格式不正确");
                    $(this).uploadifive('cancel', file);
                }
            },
            'onFallback':function(){
                return Tip('您的浏览器不支持此插件！建议使用谷歌浏览器！');
            },
            'onUpload':function(a,b,c){

            },
            'onUploadComplete':function(file,data){
                data = JSON.parse(data);
                if(data.success){
                    Tip("数据导入成功");
                }else{
                    Tip(data.error_text, 5000);
                }
                file.queueItem.remove();
            },
            'onError' : function(error, file, data) {
                Tip('文件' + file.name + '上传错误: ' + error,2000);
                file.queueItem.remove();
            }
        });
}).on('click', '.set_mcalendar', function() {
    
});