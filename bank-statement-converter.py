#!/usr/bin/env python3

import argparse
import math
import html
import os
import re
import subprocess
import sys

from decimal import *
from datetime import date

CREDIT_PARAMS = {
        'epsilonx'     : 0.01,
        'epsilony'     : 1,
        'char_width'   : 4.8,
        'char_height'  : 6.288,
        'line_spacing' : 0.912,
        'page_offset'  : 319.118,
        'dont_split'   : False
}

BANK_PARAMS = {
        'epsilonx'     : 0,
        'epsilony'     : 2,
        'char_width'   : 4.8,
        'char_height'  : 8,
        'line_spacing' : 4,
        'page_offset'  : 0,
        'dont_split'   : True
}

PARAMS = None

MONTHS = ['JAN', 'FEV', 'MAR', 'AVR', 'MAI', 'JUN',
          'JUL', 'AOU', 'SEP', 'OCT', 'NOV', 'DEC']

SUMMARY_SECTION_HEADER     = { "fr": "SOMMAIRE DES TRANSACTIONS COURANTES" }
PREV_BALANCE_LABEL         = { "fr": "Solde précédent" }
CURR_BALANCE_LABEL         = { "fr": "Nouveau solde courant =" }
TRANSACTION_SECTION_HEADER = { "fr": "DESCRIPTION DES TRANSACTIONS COURANTES" }
TRANSACTION_TABLE_HEADER   = { "fr": "Transactions effectuées avec la carte de" }
OPERATION_TABLE_HEADER     = { "fr": "Opérations au compte" }
VOLUME_SECTION_HEADER      = { "fr": "VOLUME D'ACHATS ANNUEL" }
REWARD_SECTION_HEADER      = { "fr": "PROGRAMME DE RÉCOMPENSES - CARTES DESJARDINS" }

VALID_REWARD_PATTERN = [
    "CRÉDIT DONS BONIDOLLARS",
    "CRÉDIT VOYAGE BONI DESJARDINS"
]

OFX_HEADER =  '''OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:TYPE1
ENCODING:USASCII
CHARSET:8859-1
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE
<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
<MESSAGE>OK
</STATUS>
<DTSERVER>20161221215236
<USERKEY>A49D203FCFA2AA2B
<INTU.BID>00012
<LANGUAGE>FRA
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>DESJ-2016122121523620746
<STATUS>
<CODE>0
<SEVERITY>INFO
<MESSAGE>OK
</STATUS>
<STMTRS>
<CURDEF>CAD
<BANKACCTFROM>
<BANKID>{}
<BRANCHID>{}
<ACCTID>{}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>{}0000
<DTEND>{}0000 '''

OFX_FOOTER = '''</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>{0}
<DTASOF>{1}
</LEDGERBAL>
<AVAILBAL>
<BALAMT>{0}
<DTASOF>{1}
</AVAILBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>'''

OFX_TRANSACTION = '''<STMTTRN>
<TRNTYPE>{}
<DTPOSTED>{}0000
<TRNAMT>{}
<FITID>SN;TBAGax
<NAME>{}
<MEMO>{}
</STMTTRN>'''

class Modes:
    NONE = 0
    TRANSACTIONS = 1
    OPERATIONS = 2

pageexp = re.compile('\s*<page width="(\d+\.\d+)" height="(\d+\.\d+)">\s*')
wordexp = re.compile('\s*<word xMin="(\d+\.\d+)" yMin="(\d+\.\d+)" xMax="(\d+\.\d+)" yMax="(\d+\.\d+)">(.*)</word>\s*')

class Statement:
    def __init__(self):
        self.pages = []
        self.sections = []

    def load(self, lines):
        current_page = None
        page_index = 0
        for line in lines:
            m = pageexp.match(line)
            if m:
                page_index += 1
                current_page = Page(page_index, float(m.group(1)), float(m.group(2)))
                self.pages.append(current_page)
                continue
            if not current_page:
                continue
            m = wordexp.match(line)
            if m:
                current_word = Word(float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)),
                                    m.group(5).strip(), current_page)
                current_page.words.append(current_word)

    def find_word(self, w, ymin=0):
        for page in self.pages:
            for word in page.words:
                if word.content == w and word.box.y1 >= ymin:
                    return word

    def find_words_at(self, x=None, y=None):
        words = []
        for page in self.pages:
            for word in page.words:
                if x and word.box.x1 == x:
                    words.append(word)
                if y and word.box.y1 == y:
                    words.append(word)
        return words

    def find_words_inside(self, page, x1, x2, y1, y2):
        words = []
        for word in self.pages[page].words:
            if word.box.x1 >= x1 and word.box.x2 <= x2 and \
               word.box.y1 >= y1 and word.box.y2 <= y2:
                words.append(word)
        return words

    def add_section(self, section):
        self.sections.append(section)

    def parse(self):
        self._current_section = None
        for page in statement.pages:
            for line in page.lines():
                for section in self.sections:
                    if line.startswith(section.header):
                        self._current_section = section
                        self._current_section.begin_parsing()
                if self._current_section:
                    self._current_section.parse_line(line)

class Page:
    def __init__(self, index, w, h):
        self.index = index
        self.width = w
        self.height = h
        self.words = []

    def lines(self):
        self.words = sorted(self.words, key=lambda w: w.box.y1)
        words = []
        for word in self.words:
            if words and word.box.y1 >= words[-1].box.y1 + PARAMS['epsilony']:
                yield Line(list(words))
                words = []
            words.append(word)
        if words:
            yield Line(words)

    def get_line(self, y1, y2):
        words = []
        for word in self.words:
            if word.box.y1 >= y1 - PARAMS['epsilony'] and word.box.y2 <= y2 + PARAMS['epsilony']:
                words.append(word)
        return sorted(words, key=lambda x: x.box.x1)

class Rect:
    def __init__(self, x1, x2, y1, y2):
        self.x1 = x1
        self.x2 = x2
        self.y1 = y1
        self.y2 = y2

    def mid_x(self):
        return (self.x1 + self.x2) / 2.0

    def left(self, shift=0):
        return self.x1 + shift

    def right(self, shift=0):
        return self.x2 + (shift * PARAMS['char_width'])

    def top(self):
        return self.y1

    def bottom(self):
        return self.y2

    def width(self):
        return self.x2 - self.x1

    def height(self):
        return self.y2 - self.y1

    def intersect_vert(self, x1, x2):
        return (x1 < self.x2 and x2 > self.x1)

    def __str__(self):
        return "[{0}, {1}, {2}, {3}]".format(self.x1, self.x2, self.y1, self.y2)

class Word:
    def __init__(self, xmin, ymin, xmax, ymax, content, page):
        self.box = Rect(xmin, xmax, ymin, ymax)
        self.content = html.unescape(content)
        self.page = page

    def substring(self, x1, x2):
        if PARAMS['dont_split']:
            return self.content

        if x1 < self.box.x1:
            x1 = self.box.x1
        if x2 > self.box.x2:
            x2 = self.box.x2

        left = math.floor((x1 - self.box.x1 + PARAMS['epsilonx']) / PARAMS['char_width'])
        right = math.floor((x2 - self.box.x1 + PARAMS['epsilonx']) / PARAMS['char_width'])

        return self.content[left:right]

    def get_line(self):
        return self.page.get_line(self.box.y1, self.box.y2)

    def __str__(self):
        return "<Word \"{0}\" at {1}>".format(self.content, self.box)

class Line:
    def __init__(self, words):
        self.words = words
        self.string = ""
        for word in words:
            self.string += word.content + " "

    def startswith(self, prefix):
        return self.string.startswith(prefix)

    def __str__(self):
        return self.string

class Section:
    def __init__(self, header, objects=dict()):
        self.header = header
        self.tables = []
        self.values = []
        self.objects = objects

    def add_table(self, table):
        self.tables.append(table)

    def add_value(self, value):
        self.values.append(value)

    def begin_parsing(self):
        self._current_table = None

    def parse_line(self, line):
        for value in self.values:
            if line.startswith(value.label):
                ret = value.parse_value(line.string.replace(value.label, ''))
                self.objects[value.name] = ret
                return

        for table in self.tables:
            if table.header is None or line.startswith(table.header):
                self._current_table = table
                self._current_table.begin_parsing()
        if self._current_table:
            try:
                obj = self._current_table.parse_line(line)
                if obj:
                    self.objects.append(obj)
            except:
                pass

class Value:
    def __init__(self, label, name, value_class):
        self.label = label
        self.name = name
        self._value_class = value_class

    def parse_value(self, value):
        return self._value_class(value)

class Table:
    def __init__(self, header, row_class, row_data):
        self.header = header
        self._columns = []
        self._row_class = row_class
        self._row_data = row_data

    def add_column(self, name, position, alignment, max_width, optional=False, key=False, multiline=False):
        self._columns.append(Column(name, position, alignment, max_width, optional, multiline, key))

    def begin_parsing(self):
        self._current_row = None

    def parse_line(self, line):
        row = self._current_row or Row()
        possible_line_break = False
        last_value = None
        for column in self._columns:
            if column.name in row:
                continue
            value = column.parse(line.words)
            if not value and not column.optional:
                if possible_line_break:
                    self._current_row = row
                return None
            if value and value.strip() != '':
                if column.key:
                    row.key = int(value)
                row.add_field(column.name, value)
                last_value = column.name
                possible_line_break = column.multiline
        self._current_row = None
        return self._row_class(row, self._row_data)

class Column:
    LEFT = 1
    RIGHT = 2
    CENTER = 3

    def __init__(self, name, position, alignment, max_width, optional, multiline, key):
        self.name = name
        self.position = position
        self.alignment = alignment
        self.max_width = max_width
        self.optional = optional
        self.multiline = multiline
        self.key = key

    def parse(self, words):
        if self.alignment is Column.LEFT:
            left = self.position
            right = self.position + self.max_width
        elif self.alignment is Column.RIGHT:
            left = self.position - self.max_width
            right = self.position
        elif self.alignment is Column.CENTER:
            left = self.position - (self.max_width / 2)
            right = self.position + (self.max_width / 2)

        result = []
        for word in words:
            if word.box.intersect_vert(left, right):
                result.append(word.substring(left, right)) #XXX substring(left, right))
        return ' '.join(result)

class Row:
    def __init__(self):
        self.key = None
        self._fields = dict()

    def add_field(self, name, value):
        self._fields[name] = value

    def __getitem__(self, key):
        return self._fields[key]

    def __contains__(self, key):
        return key in self._fields

    def __str__(self):
        return str(self._fields)

class Transaction:
    def __init__(self, row, statement_date):
        self.id = row['id']
        self.date = date(statement_date.year, int(row['month']), int(row['day']))
        if self.date > statement_date:
            self.date = self.date.replace(self.date.year - 1)
        self.description = row['desc']
        self.location = ""
        if 'city' in row and 'state' in row:
            self.location = row['city'] + ' ' + row['state']
        self.amount = Decimal(row['amount'].replace(' ', '').replace(',', '.'))
        if 'credit' in row:
            self.amount *= -1
        self.reward = 0
        self.valid_for_volume = True
        self.skipped = False

    def is_valid_for_volume(self):
        return self.valid_for_volume and not self.skipped

    def is_reward_spending(self):
        for pattern in VALID_REWARD_PATTERN:
            if pattern in self.description:
                return True
        return False

    def calculate_reward(self, volume, rate, extra_rate):
        if not self.is_valid_for_volume():
            return
        rate = extra_rate/100 if volume > 20000 else rate/100
        self.reward = round(rate * self.amount, 2)

    def to_csv(self):
        return "{:%Y/%m/%d},\"{}\",\"{}\",{},{},{}".format(self.date, self.description, self.location, self.amount, -1 * self.balance, self.reward)

    def __str__(self):
        return "{} - {:%Y/%m/%d} - {:25} - {:8.2f}".format(self.id, self.date, self.description, self.amount)

class Operation(Transaction):
    def __init__(self, row, statement_date):
        Transaction.__init__(self, row, statement_date)
        self.valid_for_volume = self.is_reward_spending()

class RewardSpendingTransaction(Transaction):
    def __init__(self, date, amount):
        self.id = "888"
        self.date = date
        self.description = "Crédit Bonidollars"
        self.location = ""
        self.amount = 0
        self.reward = amount

class RewardAdjustmentTransaction(Transaction):
    def __init__(self, date, amount):
        self.id = "999"
        self.date = date
        self.description = "Ajustement Bonidollars"
        self.location = ""
        self.amount = 0
        self.reward = amount

class VolumeSummary:
    def __init__(self, row, data):
        self.initial = self.parse_money(row['initial'])
        self.final = self.parse_money(row['final'])

    def parse_money(self, value):
        return Decimal(value.replace('$', '').replace(' ', '').replace(',', '.').strip())

class RewardSummary:
    def __init__(self, row, data):
        self.initial = self.parse_money(row['initial'])
        self.final = self.parse_money(row['final'])
        self.received = self.parse_money(row['received'])
        self.spent = self.parse_money(row['spent'])
        self.adjustment = self.parse_money(row['adjustment'])

    def parse_money(self, value):
        if '-' in value:
            value = '-' + value[:-1]
        return Decimal(value.replace(' ', '').replace(',', '.').strip())

class Money:
    def __init__(self, value):
        amount = re.compile("\s*\d+\.\d\d")
        self.value = amount.match(value.replace(' ', '').replace(',', '.'))
        self.value = Decimal(self.value.group())

class EOPOperation:
    def __init__(self, row, data):
        day, month = row['date'].split(' ')
        self.date = "{}{:02d}{:02d}".format(data, MONTHS.index(month) + 1, int(day))
        self.description = row['desc']

        if 'retrait' in row and row['retrait'] != '':
            self.amount = EOPOperation.parse_money(row['retrait'], -1)
        elif 'depot' in row and row['depot'] != '':
            self.amount = EOPOperation.parse_money(row['depot'])

        self.balance = EOPOperation.parse_money(row['solde'])
        self.code = row['code']
        self.reward = 0

    def parse_money(value, factor=1):
        if value.endswith('-'):
            factor *= -1
            value = value[:-1]
        return factor * Decimal(value.replace(' ', ''))

    def to_csv(self):
        withdraw = 0
        deposit = 0
        if self.amount > 0:
            deposit = self.amount
        else:
            withdraw = -1 * self.amount
        return "{},\"{}\",{},{},{}".format(self.date, self.description, deposit, withdraw, self.balance)

    def to_ofx(self):
        transaction_type = 'CREDIT'
        if self.amount < 0:
            transaction_type = 'DEBIT'

        return OFX_TRANSACTION.format(transaction_type, self.date, self.amount,
                                      self.description, self.code)

    def __str__(self):
        return "{:>7} - {:60} {:8.2f} = {:8.2f} $".format(self.date, self.description, self.amount, self.balance)

parser = argparse.ArgumentParser()
parser.add_argument("--format", choices=['csv', 'ofx', 'pretty'], default='pretty')
parser.add_argument("--input", choices=['account', 'credit'], default='account')
parser.add_argument("--language", choices=['fr', 'en'], default='fr')
parser.add_argument("--reward", default='0')
parser.add_argument("--extra-reward", default='0')
parser.add_argument("--skip", default='')
parser.add_argument("file")
args = parser.parse_args()

r = subprocess.run(['pdftotext', '-q', '-nopgbrk', '-bbox', args.file, '-'], stdout=subprocess.PIPE)
statement = Statement()
statement.load(r.stdout.decode().split('\n'))

initial_balance = None
final_balance = None

if args.input == 'account':
    PARAMS = BANK_PARAMS

    date_words = statement.find_words_inside(0, 425, 575, 37, 50)
    result = []
    start_date = ' '.join([word.content for word in date_words[1:2]])
    end_date = ' '.join([word.content for word in date_words[4:5]])
    year = date_words[-1].content

    words = statement.find_words_at(x=35.95)
    for idx, word in enumerate(words):
        line = word.get_line()
        account = line[0].content

        word = statement.find_word("reporté", ymin=word.box.y2)
        line = word.get_line()
        initial_balance = EOPOperation.parse_money(''.join([w.content for w in line[2:]]))

        page_limit = statement.pages[-1].index
        y_limit = statement.pages[-1].height
        try:
            next_word = words[idx + 1]
            page_limit = next_word.page.index
            y_limit = next_word.box.y1
        except:
            pass

        table = Table(line[0].box.bottom() + PARAMS['line_spacing'], page_limit, y_limit, EOPOperation, year)
        table.add_column('date',    69.714, Column.RIGHT, 25)
        table.add_column('code',    74.300, Column.LEFT,  23.544)
        table.add_column('desc',    98.300, Column.LEFT,  239,   multiline=True)
        table.add_column('frais',   540.00, Column.LEFT,  25,    optional=True)
        table.add_column('retrait', 447.83, Column.RIGHT, 70,    optional=True)
        table.add_column('depot',   519.78, Column.RIGHT, 70,    optional=True)
        table.add_column('solde',   587.65, Column.RIGHT, 65)

        transactions = table.parse(statement)
        break
elif args.input == 'credit':
    PARAMS = CREDIT_PARAMS

    initial_balance = 0
    word = statement.find_word("DESCRIPTION")
    word = statement.find_word("001", ymin=word.box.y2)
    word2 = statement.find_word("002", ymin=word.box.y2)
    line = word.page.get_line(word.box.y1, word.box.y2)

    date_words = statement.find_words_inside(0, 100, 195, 96, 104)
    statement_date = date(*[int(word.content) for word in reversed(date_words)])

    # Assert character dimension

    def trimmed_mean(lst):
        trimmed_lst = sorted(lst)[1:-1]
        return round(sum(trimmed_lst) / len(trimmed_lst), 3)

    char_widths = []
    char_heights = []
    for word in line:
        char_widths.append(word.box.width() / len(word.content))
        char_heights.append(word.box.height())
    indent = word2.box.y1 - word.box.y2

    assert(PARAMS['char_width'] == trimmed_mean(char_widths))
    assert(PARAMS['char_height'] == trimmed_mean(char_heights))

    # Find position of columns

    cr_shift = 0
    if line[-1].content.endswith('CR'):
        cr_shift = -2

    page_limit = statement.pages[-1].index
    y_limit = statement.pages[-1].height

    summary = Section(SUMMARY_SECTION_HEADER[args.language])
    summary.add_value(Value(PREV_BALANCE_LABEL[args.language], 'initial_balance', Money))
    summary.add_value(Value(CURR_BALANCE_LABEL[args.language], 'final_balance', Money))

    transactions = Section(TRANSACTION_SECTION_HEADER[args.language], list())

    table = Table(TRANSACTION_TABLE_HEADER[args.language], Transaction, statement_date)
    table.add_column('day',      line[0].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('month',    line[1].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('report_d', line[2].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('report_m', line[3].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('id',       line[4].box.mid_x(),     Column.CENTER, 14.4, key=True)
    table.add_column('desc',     line[5].box.left(),      Column.LEFT,   120)
    table.add_column('city',     line[5].box.left(120),   Column.LEFT,   62.4)
    table.add_column('state',    line[5].box.left(182.4), Column.LEFT,   9.6)
    table.add_column('amount',   line[-1].box.right(cr_shift), Column.RIGHT, 48)
    table.add_column('credit',   line[-1].box.right(cr_shift), Column.LEFT, 9.6, optional=True)
    transactions.add_table(table)

    table = Table(OPERATION_TABLE_HEADER[args.language], Operation, statement_date)
    table.add_column('day',      line[0].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('month',    line[1].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('report_d', line[2].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('report_m', line[3].box.mid_x(),     Column.CENTER, 9.6)
    table.add_column('id',       line[4].box.mid_x(),     Column.CENTER, 14.4, key=True)
    table.add_column('desc',     line[5].box.left(),      Column.LEFT,   192)
    table.add_column('amount',   line[-1].box.right(cr_shift), Column.RIGHT, 48)
    table.add_column('credit',   line[-1].box.right(cr_shift), Column.LEFT, 9.6, optional=True)
    transactions.add_table(table)

    volume = Section(VOLUME_SECTION_HEADER[args.language], list())
    table = Table(None, VolumeSummary, None)
    table.add_column('initial', 124.75, Column.CENTER, 100)
    table.add_column('current', 230.25, Column.CENTER, 100)
    table.add_column('final',   383.70, Column.RIGHT,  100)
    volume.add_table(table)

    reward = Section(REWARD_SECTION_HEADER[args.language], list())
    table = Table(None, RewardSummary, None)
    table.add_column('initial',    124.575, Column.CENTER, 80)
    table.add_column('received',   220.65,  Column.CENTER, 80)
    table.add_column('spent',      306.95,  Column.CENTER, 80)
    table.add_column('adjustment', 393.30,  Column.CENTER, 80)
    table.add_column('final',      489.20,  Column.CENTER, 80)
    reward.add_table(table)

    statement.add_section(summary)
    statement.add_section(transactions)
    statement.add_section(volume)
    statement.add_section(reward)
    statement.parse()
    initial_balance = summary.objects['initial_balance'].value
    final_balance = summary.objects['final_balance'].value

    if volume.objects:
        initial_volume = volume.objects[0].initial
        final_volume = volume.objects[0].final
    else:
        initial_volume = 0
        final_volume = None

    if reward.objects:
        initial_reward = reward.objects[0].initial
        final_reward = reward.objects[0].final
        received_reward = reward.objects[0].received
        spent_reward = reward.objects[0].spent
        adjustment_reward = reward.objects[0].adjustment
        assert(initial_reward + received_reward + spent_reward + adjustment_reward == final_reward)
    else:
        adjustment_reward = 0

balance = initial_balance
volume = initial_volume
total_received_reward = 0
total_spent_reward = 0
reward_rate = Decimal(args.reward)
reward_extra_rate = Decimal(args.extra_reward)
for transaction in transactions.objects:
    balance = round(balance + transaction.amount, 2)
    if args.skip and int(transaction.id) in [int(x) for x in args.skip.split(',')]:
        transaction.skipped = True
    transaction.calculate_reward(volume, reward_rate, reward_extra_rate)
    total_received_reward += transaction.reward
    if transaction.is_valid_for_volume():
        volume = round(volume + transaction.amount, 2)
    if transaction.is_reward_spending():
        total_spent_reward += transaction.amount
    if hasattr(transaction, "balance"):
        assert(balance == transaction.balance)
    transaction.balance = balance
if final_balance is not None:
    assert(balance == final_balance)
if final_volume is not None:
    assert(volume == final_volume)

# There are some unaccounted for reward spendings
if spent_reward != total_spent_reward:
    spending = RewardSpendingTransaction(statement_date, spent_reward - total_spent_reward)
    spending.balance = balance
    transactions.objects.append(spending)

# There seems to be some rounding error sometimes
if received_reward is not None:
    rounding_adjustement = received_reward - total_received_reward
    #assert(abs(rounding_adjustement) < 0.02)

adjustment_reward += rounding_adjustement
if adjustment_reward:
    adjustment = RewardAdjustmentTransaction(statement_date, adjustment_reward)
    adjustment.balance = balance
    transactions.objects.append(adjustment)

final_balance = balance
final_volume = volume

if args.format == 'pretty':
    for transaction in transactions.objects:
        print(transaction)
    print("")
    print("Initial Balance:           {:8.2f} $".format(initial_balance))
    print("Final Balance:             {:8.2f} $".format(final_balance))
    print("")
    print("Purchasing Volume:         {:8.2f} $".format(final_volume - initial_volume))
    print("")
    print("Bonidollars Reported:      {:8.2f} $".format(initial_reward))
    print("Bonidollars Received:    + {:8.2f} $".format(total_received_reward + rounding_adjustement))
    print("Bonidollars Spent:       + {:8.2f} $".format(spent_reward))
    print("Bonidollars Adjustment:  + {:8.2f} $".format(adjustment_reward))
    print("-------------------------------------")
    print("Bonidollars Balance:       {:8.2f} $".format(final_reward))
elif args.format == 'csv':
    for transaction in transactions.objects:
        print(transaction.to_csv())
elif args.format == 'ofx':
    print(OFX_HEADER)
    for transaction in transactions.objects:
        print(transaction.to_ofx())
    print(OFX_FOOTER)
