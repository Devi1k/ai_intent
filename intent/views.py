import json
import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from time import strftime, gmtime

import torch
from django.http import JsonResponse
# Create your views here.
from django.views.decorators.csrf import csrf_exempt

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
    def __init__(self, config_file='crosswoz_all.json', model_file='bert_crosswoz.zip'):
        # assert mode == 'usr' or mode == 'sys' or mode == 'all'
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'config/{}'.format(config_file))
        config = json.load(open(config_file))
        DEVICE = config['DEVICE']
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
        # if not os.path.exists(best_model_path):
        #     if not os.path.exists(output_dir):
        #         os.makedirs(output_dir)
        #     print('Load from model_file param')
        #     # archive_file = cached_path(model_file)
        #     archive_file = os.path.join(output_dir, model_file)
        #     archive = zipfile.ZipFile(archive_file, 'r')
        #     archive.extractall(root_dir)
        #     archive.close()
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
        intent_logits = intent_logits.detach().cpu().numpy()
        intent = recover_intent(self.dataloader, intent_logits[0],
                                batch_data[0][0], batch_data[0][-4])
        return intent


log.info('model loading')
nlu = BERTNLU(config_file='crosswoz_all.json')
log.info('warming up')
log.info('text:????????????A??????????????????,intent:{}'.format(nlu.predict('????????????A??????????????????')))
log.info('warm up finish. Waiting for messages')


def clean_log():
    path = 'log/'
    for i in os.listdir(path):
        if len(i) < 7:
            continue
        file_path = path + i  # ???????????????????????????
        timestamp = strftime("%Y%m%d%H%M%S", gmtime())
        # ??????????????????????????????????????????
        today_m = int(timestamp[4:6])  # ???????????????
        file_m = int(i[12:14])  # ???????????????
        today_y = int(timestamp[0:4])  # ???????????????
        file_y = int(i[7:11])  # ???????????????
        # ????????????????????????????????????????????????
        # print(file_path)
        if file_m < today_m:
            if os.path.exists(file_path):  # ?????????????????????????????????????????????
                os.remove(file_path)  # ????????????
        elif file_y < today_y:
            if os.path.exists(file_path):
                os.remove(file_path)


@csrf_exempt
def intent_cls(request):
    # print(request.method)
    log.info('*' * 5 + 'clean log' + '*' * 5)
    clean_log()
    log.info('-----------------------------------------------------------')
    if request.method == 'GET':
        raw_text = request.GET.get('text')
        intent = nlu.predict(raw_text)
        log.info('text:{},intent:{}'.format(raw_text, intent))
        return JsonResponse({'message': 'success', 'data': intent, 'code': 0})
    return JsonResponse({'message': 'unknown methods',
                         'code': 50012})
