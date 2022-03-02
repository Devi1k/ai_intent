from time import strftime, gmtime

from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
# Create your views here.
from django.views.decorators.csrf import csrf_exempt
import os
import zipfile
import json
import torch
import logging
import re
from logging.handlers import TimedRotatingFileHandler
# from convlab2.util.file_util import cached_path
from nlp_cls.IntentNLU import NLU
from nlp_cls.dataloader import Dataloader
from nlp_cls.jointBERT import JointBERT
from nlp_cls.postprocess import recover_intent

LOG_PATH = os.getcwd() + '/log/intent'
log_fmt = '%(asctime)s\tFile \"%(filename)s\",line %(lineno)s\t%(levelname)s: %(message)s'
formatter = logging.Formatter(log_fmt)
log = logging.getLogger()
log.setLevel(logging.INFO)
log.suffix = "%Y-%m-%d_%H-%M.log"
log.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}.log$")
log_file_handler = TimedRotatingFileHandler(filename=LOG_PATH, when="D", interval=1, backupCount=7)
log_file_handler.setFormatter(formatter)
log.addHandler(log_file_handler)


class BERTNLU(NLU):
    def __init__(self, config_file='crosswoz_all.json'):
        # assert mode == 'usr' or mode == 'sys' or mode == 'all'
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'config/{}'.format(config_file))
        config = json.load(open(config_file))
        DEVICE = config['DEVICE'] if torch.cuda.is_available() else 'cpu'
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(root_dir, config['data_dir'])
        output_dir = os.path.join(root_dir, config['output_dir'])

        # if not os.path.exists(os.path.join(data_dir, 'intent_vocab.json')):
        #     preprocess()

        intent_vocab = json.load(open(os.path.join(data_dir, 'intent_vocab.json')))
        dataloader = Dataloader(intent_vocab=intent_vocab,
                                pretrained_weights=config['model']['pretrained_weights'])

        print('intent num:', len(intent_vocab))

        best_model_path = os.path.join(output_dir, 'pytorch_model.bin')
        print('Load from', best_model_path)
        model = JointBERT(config['model'], DEVICE, dataloader.intent_dim)
        model.load_state_dict(torch.load(os.path.join(output_dir, 'pytorch_model.bin'), DEVICE))
        model.to(DEVICE)
        model.eval()

        self.model = model
        self.dataloader = dataloader
        print("BERTNLU loaded")

    def predict(self, utterance, context=list()):
        ori_word_seq = self.dataloader.tokenizer.tokenize(utterance)
        # ori_tag_seq = ['O'] * len(ori_word_seq)
        context_size = 1
        context_seq = self.dataloader.tokenizer.encode('[CLS] ' + ' [SEP] '.join(context[-context_size:]))
        intents = []
        da = {}

        word_seq, new2ori = ori_word_seq, None
        batch_data = [[ori_word_seq, intents, da, context_seq,
                       new2ori, word_seq, self.dataloader.seq_intent2id(intents)]]

        pad_batch = self.dataloader.pad_batch(batch_data)
        pad_batch = tuple(t.to(self.model.device) for t in pad_batch)
        word_seq_tensor, intent_tensor, word_mask_tensor, context_seq_tensor, context_mask_tensor = pad_batch
        context_seq_tensor, context_mask_tensor = None, None
        intent_logits = self.model.forward(word_seq_tensor, word_mask_tensor,
                                           context_seq_tensor=context_seq_tensor,
                                           context_mask_tensor=context_mask_tensor)[0]
        intent = recover_intent(self.dataloader, intent_logits[0],
                                batch_data[0][0], batch_data[0][-4])
        return intent[0][0]


nlu = BERTNLU(config_file='crosswoz_all.json')
log.info('warming up')
log.info(nlu.predict('查询移民融入服务站及相关信息'))


def clean_log():
    path = 'log/'
    for i in os.listdir(path):
        if len(i) < 4:
            continue
        file_path = path + i  # 生成日志文件的路径
        timestamp = strftime("%Y%m%d%H%M%S", gmtime())
        # 获取日志的年月，和今天的年月
        today_m = int(timestamp[4:6])  # 今天的月份
        file_m = int(i[9:11])  # 日志的月份
        today_y = int(timestamp[0:4])  # 今天的年份
        file_y = int(i[4:8])  # 日志的年份
        # 对上个月的日志进行清理，即删除。
        # print(file_path)
        if file_m < today_m:
            if os.path.exists(file_path):  # 判断生成的路径对不对，防止报错
                os.remove(file_path)  # 删除文件
        elif file_y < today_y:
            if os.path.exists(file_path):
                os.remove(file_path)


@csrf_exempt
def intent_cls(request):
    # print(request.method)
    clean_log()
    log.info('-----------------------------------------------------------')
    if request.method == 'POST':
        raw_text = request.POST.get('text')
        # print(raw_text)
        intent = nlu.predict(raw_text)
        return JsonResponse({'message': 'success', 'data': intent, 'code': 0})
    return JsonResponse({'message': 'unknown methods',
                         'code': 50012})