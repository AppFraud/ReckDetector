from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim
import datetime
import pickle
import numpy
import re


# Preprocess text
def filter_chinese(text):
    # result = re.findall('[\u4e00-\u9fa50-9,.!?，。！？]', text)
    result = re.findall('[\u4e00-\u9fa5]', text)
    output = ''.join(result)
    return output


def get_sim_score(pre_model, text):
    with open('DetectReck/resources/red_packet_text.txt', 'r', encoding='UTF-8') as f:
        samples = f.read().split()
    with open('DetectReck/resources/red_packet_text.pkl', 'rb') as f:
        samples_embedding = pickle.load(f)
    pre_text = filter_chinese(text)
    # print(pre_text)
    # Encode text into vectors
    embedding = pre_model.encode(pre_text)
    cosine_sim = cos_sim(embedding, samples_embedding)
    sim_scores = cosine_sim[0].numpy()
    # Get the score for the most similar text
    max_score = max(sim_scores)
    # print('Maximum similarity score: ', max_score)
    index = numpy.where(sim_scores == max_score)
    # Get the most similar red packet text
    sim_text = samples[index[0][0]]
    # print('The most similar red packet text：', sim_text)
    return max_score, sim_text


# if __name__ == '__main__':
#     start_time0 = datetime.datetime.now()
#     model = SentenceTransformer('resources/paraphrase-multilingual-MiniLM-L12-v2')
#     end_time0 = datetime.datetime.now()
#     time0 = (end_time0 - start_time0).seconds + (end_time0 - start_time0).microseconds / 1000000
#     print('加载模型的时间：', time0)
#
#     start_time = datetime.datetime.now()
#     origin_text = '邀请新用户领取！！！'
#     score, match_text = get_sim_score(model, origin_text)
#
#     if round(score, 2) >= numpy.float32(0.6):
#         print("匹配成功！")
#
#     end_time = datetime.datetime.now()
#     time2 = (end_time - start_time).seconds + (end_time - start_time).microseconds / 1000000
#     print("时间消费：", time2, "s")
