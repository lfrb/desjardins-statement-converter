#!/usr/bin/env python3

import argparse
import math
import os
import re
import subprocess
import sys

CREDIT_PARAMS = {
        'epsilonx'     : 0.01,
        'epsilony'     : 1,
        'char_width'   : 4.8,
        'char_height'  : 6.288,
        'line_spacing' : 0.912,
        'page_offset'  : 322.068000,
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

    def parse(self, lines):
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

class Page:
    def __init__(self, index, w, h):
        self.index = index
        self.width = w
        self.height = h
        self.words = []

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
        self.content = content
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

class Table:
    def __init__(self, position, page_limit, y_limit, row_class, row_data):
        self.position = position
        self.page_limit = page_limit
        self.y_limit = y_limit
        self._columns = []
        self._row_class = row_class
        self._row_data = row_data

    def add_column(self, name, position, alignment, max_width, optional=False, key=False, multiline=False):
        self._columns.append(Column(name, position, alignment, max_width, optional, multiline, key))

    def _parse_line(self, words, row=None):
        if not row:
            row = Row()
        possible_line_break = False
        last_value = None
        for column in self._columns:
            if column.name in row:
                continue
            value = column.parse(words)
            if not value and not column.optional:
                return row, possible_line_break
            if value and value.strip() != '':
                if column.key:
                    row.key = int(value)
                row.add_field(column.name, value)
                last_value = column.name
                possible_line_break = column.multiline
        return row, False

    def parse(self, statement):
        y = self.position
        objects = []
        row = None
        for page in statement.pages:
            while y <= page.height:
                line = page.get_line(y, y + PARAMS['char_height'])
                if line:
                    string = ""
                    for word in line:
                        string += word.content + " "
                    #print(string)

                    y = line[0].box.y1
                    try:
                        row, partial = self._parse_line(line, row)
                        if row and not partial:
                            obj = self._row_class(row, self._row_data)
                            objects.append(obj)
                            row = None
                    except Exception as e:
                        row = None
                        pass
                y += PARAMS['char_height'] + PARAMS['line_spacing']
                if page.index >= self.page_limit and y >= self.y_limit:
                    return objects
            y = PARAMS['page_offset']
        return objects

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
    def __init__(self, row, data):
        self.id = row['id']
        self.date = "{}{:02d}{:02d}".format(data, int(row['month']), int(row['day']))
        self.description = row['desc']
        self.location = row['city'] + ' ' + row['state']
        self.amount = float(row['amount'].replace(' ', '').replace(',', '.'))
        if 'credit' in row:
            self.amount *= -1

    def to_csv(self):
        withdraw = 0
        deposit = 0
        if self.amount > 0:
            deposit = self.amount
        else:
            withdraw = -1 * self.amount
        return "{},\"{} {}\",{},{},{}".format(self.date, self.description, self.location, deposit, withdraw, self.balance)

    def __str__(self):
        return "{} - {} - {:25} - {:8.2f}".format(self.id, self.date, self.description, self.amount)

class Operation:
    def __init__(self, row, data):
        day, month = row['date'].split(' ')
        self.date = "{}{:02d}{:02d}".format(data, MONTHS.index(month) + 1, int(day))
        self.description = row['desc']

        if 'retrait' in row and row['retrait'] != '':
            self.amount = Operation.parse_money(row['retrait'], -1)
        elif 'depot' in row and row['depot'] != '':
            self.amount = Operation.parse_money(row['depot'])

        self.balance = Operation.parse_money(row['solde'])
        self.code = row['code']

    def parse_money(value, factor=1):
        if value.endswith('-'):
            factor *= -1
            value = value[:-1]
        return factor * float(value.replace(' ', ''))

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
parser.add_argument("file")
args = parser.parse_args()

r = subprocess.run(['pdftotext', '-q', '-nopgbrk', '-bbox', args.file, '-'], stdout=subprocess.PIPE)
statement = Statement()
statement.parse(r.stdout.decode().split('\n'))

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
        #print(account)

        word = statement.find_word("reporté", ymin=word.box.y2)
        line = word.get_line()
        initial_balance = Operation.parse_money(''.join([w.content for w in line[2:]]))

        page_limit = statement.pages[-1].index
        y_limit = statement.pages[-1].height
        try:
            next_word = words[idx + 1]
            page_limit = next_word.page.index
            y_limit = next_word.box.y1
        except:
            pass

        table = Table(line[0].box.bottom() + PARAMS['line_spacing'], page_limit, y_limit, Operation, year)
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

    date_words = statement.find_words_inside(0, 170, 195, 96, 104)
    year = date_words[-1].content

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

    table = Table(line[0].box.top(), page_limit, y_limit, Transaction, year)
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

    transactions = table.parse(statement)


balance = initial_balance
for transaction in transactions:
    balance = round(balance + transaction.amount, 2)
    transaction.balance = balance
    if hasattr(transaction, "balance"):
        assert(balance == transaction.balance)
final_balance = balance

if args.format == 'pretty':
    print("Initial Balance: {:n} $".format(initial_balance))
    for transaction in transactions:
        print(transaction)
elif args.format == 'csv':
    for transaction in transactions:
        print(transaction.to_csv())
elif args.format == 'ofx':
    print(OFX_HEADER)
    for transaction in transactions:
        print(transaction.to_ofx())
    print(OFX_FOOTER)
