from bs4 import BeautifulSoup
import json
import requests

class ZMWError(Exception):
    def __init__(self, message):
        self.message = message

class ZebraMotionWorks:

    def __init__(self, year, event_spec, match_type, match_number):
        if match_type == "Qualification":
            match_spec = "qm"
        # TODO: add other options
        self.url = (f"https://www.thebluealliance.com/match/{year}{event_spec}_{match_spec}{match_number}")
        self.get_motionworks_data()

    def get_motionworks_data(self):
        try:
            with requests.get(self.url) as response:
                if response.status_code != 200:
                    raise ZMWError("error code %d" % response.status_code)
                content = response.text
        except requests.exceptions.ConnectionError:
            raise ZMWError("could not connect to TheBlueAlliance.")
        soup = BeautifulSoup(content, "html.parser")

        raw_data = soup.find("div", {"class": "zebramotionworks-content"})["data-zebramotionworks"]
        data = json.loads(raw_data)

        alliances = {"blue": {}, "red": {}}

        for alliance_name in ["red", "blue"]:
            for team in data["alliances"][alliance_name]:
                alliances[alliance_name][team["team_key"]] = list(zip(team["xs"], team["ys"]))
        
        self.data = alliances
        self.times = data["times"]

    def closest_time_index(self, t_p):
        # not really closest but whatever
        for i, t in enumerate(self.times):
            if t >= t_p:
                return i
        return len(self.times) - 1

if __name__ == "__main__":
    zmw = ZebraMotionWorks(2020, "wasno", "Qualification", 20)
    for alliance_name in ["red", "blue"]:
        print(alliance_name)
        for team in zmw.data[alliance_name].keys():
            print(team, zmw.data[alliance_name][team][0])